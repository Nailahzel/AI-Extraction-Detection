"""Calibrate fair baselines, freeze settings, then evaluate unfamiliar scenarios."""

import argparse
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics

from modelshield.config import ROOT
from modelshield.engine import POLICY_PATH, RiskEngine
from modelshield.model import SentimentModel
from scripts.challenge_traffic import PROFILES, challenge
from scripts.experiment_support import fingerprint
from scripts.evaluate import wilson

CONFIGURATIONS = ("disabled", "rate_only", "four_signals", "full")
RATE_LIMITS = (5, 10, 20, 40, 60, 100, 160, 240, 400, 1000)
THRESHOLDS = (35, 45, 55, 65, 75, 80, 85, 90, 95, 100)


def replay(model, scenario, configuration, setting, base_policy):
    clients = {q["key"]: "Unlabeled client" for q in scenario["queries"]}
    policy = deepcopy(base_policy)
    if configuration in {"four_signals", "full"}:
        policy["throttle_threshold"] = setting
        # Both behavioral variants use the same two-second response, so this
        # comparison isolates detection, not unequal cooldown durations.
        policy["block_threshold"] = 101
    engine = RiskEngine(model, clients, policy, correlate=configuration == "full")
    windows = {key: deque() for key in clients}
    next_at = {key: 0 for key in clients}
    first = None
    denied = attempted = 0
    for query in scenario["queries"]:
        at = (
            max(query["at"], next_at[query["key"]])
            if scenario["respect_retry_after"]
            else query["at"]
        )
        if at >= scenario["duration"]:
            continue
        attempted += 1
        now, key = 1000 + at, query["key"]
        action, retry = "allow", 0
        if configuration == "rate_only":
            window = windows[key]
            while window and window[0] <= at - 60:
                window.popleft()
            if len(window) >= setting:
                action, retry = "throttled", max(1, math.ceil(window[0] + 60 - at))
            else:
                window.append(at)
        elif configuration != "disabled":
            action, retry = engine.gate(key, now)
            if action == "allow":
                engine.observe(key, query["text"], model.predict(query["text"])[1], now)
                action, retry = engine.enforce(key, now)
        if action != "allow":
            denied += 1
            if first is None:
                first = at
            if scenario["respect_retry_after"]:
                next_at[key] = at + retry
    return {
        "profile": scenario["profile"],
        "seed": scenario["seed"],
        "attack": scenario["attack"],
        "flagged": first is not None,
        "first_denial_seconds": first,
        "attempted": attempted,
        "allowed": attempted - denied,
        "denied": denied,
    }


def summarize(rows):
    attacks = [r for r in rows if r["attack"]]
    benign = [r for r in rows if not r["attack"]]
    detected = sum(r["flagged"] for r in attacks)
    fp = sum(r["flagged"] for r in benign)
    times = [r["first_denial_seconds"] for r in attacks if r["flagged"]]
    return {
        "attack_sessions": len(attacks),
        "benign_sessions": len(benign),
        "detected": detected,
        "false_positives": fp,
        "detection_rate": detected / len(attacks) if attacks else None,
        "false_positive_rate": fp / len(benign) if benign else None,
        "detection_ci95": wilson(detected, len(attacks)) if attacks else None,
        "false_positive_ci95": wilson(fp, len(benign)) if benign else None,
        "median_detection_seconds": statistics.median(times) if times else None,
        "legitimate_allowed": sum(r["allowed"] for r in benign),
        "legitimate_attempted": sum(r["attempted"] for r in benign),
    }


def choose(candidates):
    feasible = [row for row in candidates if row["false_positive_rate"] <= 0.05]
    if not feasible:
        raise ValueError(
            "No candidate met the calibration false-positive target; expand the calibration protocol explicitly."
        )
    return max(
        feasible,
        key=lambda r: (
            r["detection_rate"],
            -r["false_positive_rate"],
            -(
                r["median_detection_seconds"]
                if r["median_detection_seconds"] is not None
                else 999
            ),
            r["setting"],
        ),
    )


def calibrate(output):
    model = SentimentModel()
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    sessions = [
        challenge(p, seed, "calibration") for p in PROFILES for seed in range(210, 214)
    ]
    configurations, trials = {"disabled": None}, {}
    for configuration in CONFIGURATIONS[1:]:
        candidates = []
        for setting in RATE_LIMITS if configuration == "rate_only" else THRESHOLDS:
            rows = [replay(model, s, configuration, setting, policy) for s in sessions]
            candidates.append({"setting": setting, **summarize(rows)})
        selected = choose(candidates)
        configurations[configuration] = selected["setting"]
        trials[configuration] = candidates
        print(
            f"Calibration {configuration}: {selected['setting']}; DR={selected['detection_rate']:.2%}, FP={selected['false_positive_rate']:.2%}",
            flush=True,
        )
    protocol = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "calibration_sha256": fingerprint(sessions),
        "engine_sha256": fingerprint(
            (ROOT / "modelshield" / "engine.py").read_text(encoding="utf-8")
        ),
        "generator_sha256": fingerprint(
            (ROOT / "scripts" / "challenge_traffic.py").read_text(encoding="utf-8")
        ),
        "calibration_seeds": [210, 213],
        "challenge_seeds": [31000, 31005],
        "policy": policy,
        "model": model.metadata(),
        "settings": configurations,
        "candidates": trials,
        "selection_rule": "Calibration FP <=5%; maximize detection, then minimize FP, then detection time; ties prefer less sensitivity.",
        "rate_definition": "Fixed 60-second sliding window of admitted requests per key, independently calibrated capacity.",
        "behavioral_response": "Both variants use 2-second throttles; no 30-second block in this ablation. Production policy is unchanged.",
    }
    output.mkdir(parents=True, exist_ok=True)
    path = output / "comparison-protocol.json"
    path.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    return path


def load_external(path):
    sessions = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for scenario in sessions:
        if (
            type(scenario.get("attack")) is not bool
            or not isinstance(scenario.get("queries"), list)
            or not scenario["queries"]
        ):
            raise ValueError(
                "Each session needs a boolean attack label and nonempty queries."
            )
        if (
            not isinstance(scenario.get("profile"), str)
            or not isinstance(scenario.get("seed"), int)
            or not isinstance(scenario.get("respect_retry_after"), bool)
        ):
            raise ValueError(
                "Each session needs profile, seed, and respect_retry_after metadata."
            )
        duration = scenario.get("duration")
        if (
            not isinstance(duration, (float, int))
            or not math.isfinite(duration)
            or not 0 < duration <= 300
        ):
            raise ValueError("Session duration must be finite and within 300 seconds.")
        previous = -1
        for query in scenario["queries"]:
            at = query.get("at")
            if (
                not isinstance(at, (int, float))
                or not math.isfinite(at)
                or at < previous
                or at < 0
            ):
                raise ValueError(
                    "Queries require ordered finite nonnegative timestamps."
                )
            previous = at
            if (
                not isinstance(query.get("key"), str)
                or not query["key"]
                or not isinstance(query.get("text"), str)
                or not 0 < len(query["text"].strip()) <= 2000
            ):
                raise ValueError("Queries require a key and valid text.")
    return sessions


def evaluate(protocol_path, output, external=None):
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    model = SentimentModel()
    if (
        fingerprint((ROOT / "modelshield" / "engine.py").read_text(encoding="utf-8"))
        != protocol["engine_sha256"]
        or fingerprint(
            (ROOT / "scripts" / "challenge_traffic.py").read_text(encoding="utf-8")
        )
        != protocol["generator_sha256"]
    ):
        raise ValueError(
            "Detector or scenario source changed after calibration. Freeze a new protocol explicitly."
        )
    if model.metadata() != protocol["model"]:
        raise ValueError(
            "Model changed since calibration. Freeze a new protocol explicitly."
        )
    sessions = (
        load_external(external)
        if external
        else [
            challenge(p, seed, "challenge")
            for p in PROFILES
            for seed in range(31000, 31006)
        ]
    )
    calibration_texts = {
        q["text"]
        for p in PROFILES
        for seed in range(210, 214)
        for q in challenge(p, seed, "calibration")["queries"]
    }
    if any(q["text"] in calibration_texts for s in sessions for q in s["queries"]):
        raise ValueError("Challenge contains exact calibration inputs.")
    if {s["attack"] for s in sessions} != {True, False}:
        raise ValueError(
            "Evaluation requires both attack and legitimate sessions to measure detection and false positives."
        )
    results = []
    for configuration, setting in protocol["settings"].items():
        rows = [
            replay(model, s, configuration, setting, protocol["policy"])
            for s in sessions
        ]
        result = {
            "configuration": configuration,
            "setting": setting,
            **summarize(rows),
            "sessions": rows,
        }
        results.append(result)
        print(
            f"Challenge {configuration}: DR={result['detection_rate']:.2%}, FP={result['false_positive_rate']:.2%}",
            flush=True,
        )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "saved synthetic challenge comparison",
        "protocol_sha256": fingerprint(protocol),
        "dataset_sha256": fingerprint(sessions),
        "protocol": protocol,
        "dataset_origin": (
            str(external)
            if external
            else "New locally authored challenge families; not an independent teammate dataset"
        ),
        "results": results,
        "limitations": [
            "Virtual-clock replay, not end-to-end HTTP latency.",
            "Settings selected only on calibration; inspected challenge results become regression evidence on subsequent runs.",
            "All variants see the same proposed input sequence; patient clients postpone later inputs after a denial within the fixed time budget.",
            "Ground truth is kept outside the detector. Similar observable behavior can have different intent.",
            "Synthetic confidence and shared generator families limit generalization; independent teammate scenarios remain a separate validation step.",
        ],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "defense-comparison.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["calibrate", "evaluate", "all"], default="all"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "reports")
    parser.add_argument("--protocol", type=Path)
    parser.add_argument(
        "--challenge",
        type=Path,
        help="Independent evaluator JSONL sessions; used only after calibration.",
    )
    args = parser.parse_args()
    path = args.protocol or args.output / "comparison-protocol.json"
    if args.phase in {"all", "calibrate"}:
        path = calibrate(args.output)
    if args.phase in {"all", "evaluate"}:
        evaluate(path, args.output, args.challenge)
