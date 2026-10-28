"""Read-only evidence for the jury, with saved measurements kept separate from live state."""

from datetime import datetime, timezone
import json
import math

from .chat_engine import POLICY as CHAT_POLICY
from .config import ROOT
from .traffic import PROFILES

REPORTS_DIR = ROOT / "reports"
REPORT_FILES = {
    "chat-quality": "chat-evaluation.json",
    "classifier-challenges": "defense-comparison.json",
    "classifier-regression": "evaluation.json",
    "chat-browser": "chat-check.json",
    "chat-demo": "probing-questions-attack.json",
    "chat-protection": "protection-check.json",
    "chat-feature-demo": "chat-feature-demo.json",
}


def reject_constant(value):
    raise ValueError(f"Non-finite value: {value}")


def load_report(name):
    path = REPORTS_DIR / REPORT_FILES[name]
    try:
        if path.stat().st_size > 5_000_000:
            raise ValueError("Report is too large")
        data = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=reject_constant
        )
        if not isinstance(data, dict):
            raise ValueError("Report must be an object")
        return {
            "available": True,
            "data": data,
            "saved_at": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(),
        }
    except (OSError, UnicodeError, ValueError):
        return {"available": False, "message": "Saved report is missing or unreadable."}


def quality_report(name, report, service):
    descriptions = {
        "chat-quality": (
            "Chat · development scenarios",
            "chat",
            "Standard access without bulk passes; throttle/block outcomes on a virtual clock. No language-model generation, actual waiting or independent holdout.",
        ),
        "classifier-challenges": (
            "Classifier · challenge scenarios",
            "classifier",
            "New locally authored synthetic challenges, separate from calibration. Not independently collected customer traffic.",
        ),
        "classifier-regression": (
            "Classifier · earlier regression",
            "classifier",
            "Previously inspected scenarios reused for regression. These optimistic figures do not validate the chatbot or unfamiliar traffic.",
        ),
    }
    title, model_scope, scope = descriptions[name]
    summary = {
        "id": name,
        "title": title,
        "model_scope": model_scope,
        "scope": scope,
        "available": False,
        "message": report.get(
            "message", "Report has incomplete or inconsistent measurements."
        ),
    }
    if not report["available"]:
        return summary
    data = report["data"]
    try:
        if name == "classifier-challenges":
            result = next(
                row for row in data["results"] if row["configuration"] == "full"
            )
            detected = result["detected"]
            matches = (
                data["protocol"]["policy"] == service.engine.policy
                and data["protocol"]["model"]["fingerprint"]
                == service.model.metadata()["fingerprint"]
            )
        elif name == "classifier-regression":
            result = data["test"]
            detected = result["detected_attacks"]
            matches = (
                data["policy"] == service.engine.policy
                and data["model"]["fingerprint"]
                == service.model.metadata()["fingerprint"]
            )
        else:
            result = data
            detected = result["detected_attacks"]
            matches = data["policy"] == CHAT_POLICY
        attacks, benign, false_positives = (
            result["attack_sessions"],
            result["benign_sessions"],
            result["false_positives"],
        )
        if any(
            type(value) is not int
            for value in [attacks, benign, detected, false_positives]
        ):
            raise ValueError("Counts must be integers")
        if (
            attacks <= 0
            or benign <= 0
            or not 0 <= detected <= attacks
            or not 0 <= false_positives <= benign
        ):
            raise ValueError("Invalid counts")
        for key, expected in [
            ("detection_rate", detected / attacks),
            ("false_positive_rate", false_positives / benign),
        ]:
            if type(result[key]) not in (int, float) or not math.isclose(
                result[key], expected, abs_tol=0.0001
            ):
                raise ValueError("Rate does not match counts")
        summary.update(
            available=True,
            saved_at=report["saved_at"],
            attack_sessions=attacks,
            benign_sessions=benign,
            detected_attacks=detected,
            false_positives=false_positives,
            detection_rate=detected / attacks,
            false_positive_rate=false_positives / benign,
            configuration_matches=matches,
            configuration_scope=(
                "chat policy"
                if name == "chat-quality"
                else "classifier policy and model fingerprint"
            ),
        )
        summary.pop("message", None)
        if name == "chat-quality":
            profiles = data.get("profiles", {})
            summary["profiles"] = [
                {
                    "name": key.replace("_", " "),
                    "sessions": row["sessions"],
                    "flagged": row["flagged"],
                }
                for key, row in profiles.items()
                if isinstance(row, dict)
                and type(row.get("sessions")) is int
                and type(row.get("flagged")) is int
                and 0 <= row["flagged"] <= row["sessions"]
            ]
    except (KeyError, TypeError, ValueError, StopIteration, AttributeError):
        summary["available"] = False
        summary["message"] = "Report has incomplete or inconsistent measurements."
    return summary


def build_evidence(service):
    reports = {name: load_report(name) for name in REPORT_FILES}
    quality = [
        quality_report(name, reports[name], service)
        for name in ("chat-quality", "classifier-challenges", "classifier-regression")
    ]
    generators = {
        "classifier_available": (ROOT / "scripts/simulate.py").is_file(),
        "chat_available": (ROOT / "scripts/chat_traffic.py").is_file(),
        "classifier_profiles": PROFILES,
        "chat_profiles": ["normal", "extraction"],
    }
    requirements = [
        {
            "id": "inference",
            "title": "Working model API",
            "implemented": True,
            "requirement": "A working inference API in front of a small open-source text or image classifier.",
            "proof": "The included text classifier is loaded behind the authenticated prediction API. A separate local Qwen API powers conversations.",
        },
        {
            "id": "traffic",
            "title": "Normal + attack traffic",
            "implemented": generators["classifier_available"],
            "requirement": "A traffic generator with normal users and an extraction attacker.",
            "proof": "Repeatable generators produce ordinary requests and extraction-like bursts, diverse inputs, or boundary probes. Manual chat batches send real HTTP requests.",
        },
        {
            "id": "signals",
            "title": "Multiple detection signals",
            "implemented": len(service.engine.policy["weights"]) >= 3,
            "requirement": "A detector using at least 2–3 signals.",
            "proof": "The classifier combines four signals and cross-key correlation. Chat has its own three request-side signals.",
        },
        {
            "id": "alerts",
            "title": "Real-time alerts",
            "implemented": True,
            "requirement": "Console alerts, dashboard evidence, or automatic throttling of suspicious keys.",
            "proof": "The monitoring page shows live restrictions and recorded reasons. Chat enforcement returns HTTP 429, with a retry delay and no answer.",
        },
        {
            "id": "quality",
            "title": "Measured quality",
            "implemented": any(
                row["available"] and row["model_scope"] == "classifier"
                for row in quality
            ),
            "requirement": "Detection rate and false-positive rate measured on generated traffic.",
            "proof": "Saved reports contain session counts, both rates, and failure cases. Chat and classifier measurements are labeled separately.",
        },
    ]
    browser = {"available": False}
    raw = reports["chat-browser"]
    if raw["available"]:
        data = raw["data"]
        if (
            type(data.get("passed")) is int
            and isinstance(data.get("checks"), list)
            and data["passed"] == len(data["checks"])
            and all(isinstance(check, str) for check in data["checks"])
            and data.get("browser_errors") == []
        ):
            browser = {
                "available": True,
                "passed": data["passed"],
                "checks": data["checks"],
                "saved_at": raw["saved_at"],
                "scope": "Saved real-model browser integration run; not a detection-accuracy benchmark.",
            }
    demo = {"available": False}
    raw = reports["chat-demo"]
    if raw["available"]:
        data = raw["data"]
        try:
            counts, client = data["http_status_counts"], data["client_at_capture"]
            if (
                type(data["request_count"]) is not int
                or any(type(n) is not int or n < 0 for n in counts.values())
                or sum(counts.values()) != data["request_count"]
            ):
                raise ValueError("Inconsistent response counts")
            if (
                not isinstance(client["risk"], (int, float))
                or not 0 <= client["risk"] <= 100
            ):
                raise ValueError("Invalid risk")
            demo = {
                "available": True,
                "saved_at": raw["saved_at"],
                "requests": data["request_count"],
                "answered": counts.get("200", 0),
                "withheld": counts.get("429", 0),
                "risk": client["risk"],
                "other_client_status": data.get("other_client_status"),
                "scope": "A saved manual chat burst. These figures are separate from current session counters.",
            }
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
    protection = {"available": False}
    raw = reports["chat-protection"]
    if raw["available"]:
        data = raw["data"]
        if (type(data.get("passed")) is int and data["passed"] > 0
                and isinstance(data.get("checks"), list)
                and data["passed"] == len(data["checks"])
                and all(isinstance(check, str) for check in data["checks"])
                and data.get("browser_errors") == []):
            protection = {"available": True, "passed": data["passed"], "checks": data["checks"],
                          "saved_at": raw["saved_at"], "configuration_matches": data.get("policy") == CHAT_POLICY,
                          "scope": "Saved real-model/browser integration of waiting, bulk approval and restriction. Fixed scenarios, not a detection-accuracy or copying-success benchmark."}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requirements": requirements,
        "implemented_count": sum(row["implemented"] for row in requirements),
        "coverage_note": "Implementation coverage is not an accuracy score or a jury grading decision.",
        "inference": {
            "classifier": service.model.metadata(),
            "chat": service.chat.runtime.status(),
            "classifier_endpoint": "POST /predict",
            "chat_endpoint": "POST /chat/messages",
            "access": "API-key authentication",
            "classifier_source_license": "MIT project source and original synthetic corpus",
        },
        "traffic": generators,
        "policies": {"chat": CHAT_POLICY, "classifier": service.engine.policy},
        "quality": quality,
        "browser": browser,
        "demo": demo,
        "protection": protection,
    }
