"""Calibrate on separate sessions, then replay the fixed regression traffic.

The benchmark uses a virtual clock and no sleep. It replays the same detector
used by the API in observe mode; time-to-detect is simulated arrival time.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np

from modelshield.config import DEMO_KEYS, ROOT
from modelshield.engine import POLICY_PATH, RiskEngine
from modelshield.model import SentimentModel
from modelshield.traffic import ATTACKS, PROFILES, session

CALIBRATION_SEEDS = range(100, 112)
TEST_SEEDS = range(10000, 10030)
CANDIDATES = [55, 60, 65, 70, 75]
REGRESSION_NOTE = "The v2 sentiment update reuses the previously inspected v1 holdout as a fixed regression suite; these are not new unseen test sessions. Sarcasm regression examples are separate from this extraction-traffic benchmark."


def trace_session(model, profile, seed, split, policy):
    engine = RiskEngine(model, DEMO_KEYS, policy=policy)
    trace = []
    for query in session(profile, seed, split, duration=45):
        _, confidence = model.predict(query.text)
        engine.observe(query.key, query.text, confidence, query.at + 1000)
        risk = max(state.risk for state in engine.clients.values())
        trace.append((query.at, risk))
        # Threshold candidates stop at 75. Once all are crossed, further attack
        # traffic cannot affect session detection or first-detection latency.
        if profile in ATTACKS and risk >= max(CANDIDATES):
            break
    return {
        "profile": profile,
        "seed": seed,
        "attack": profile in ATTACKS,
        "trace": trace,
    }


def wilson(successes, total):
    if not total:
        return [0.0, 0.0]
    z, fraction = 1.96, successes / total
    denominator = 1 + z * z / total
    center = (fraction + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(fraction * (1 - fraction) / total + z * z / (4 * total * total))
        / denominator
    )
    return [round(max(0, center - margin), 4), round(min(1, center + margin), 4)]


def summarize(traces, threshold):
    rows = []
    for item in traces:
        first = next((at for at, risk in item["trace"] if risk >= threshold), None)
        rows.append(
            {
                "profile": item["profile"],
                "seed": item["seed"],
                "attack": item["attack"],
                "detected": first is not None,
                "time_to_detect": first,
                "peak_risk": max(risk for _, risk in item["trace"]),
            }
        )
    attacks = [row for row in rows if row["attack"]]
    benign = [row for row in rows if not row["attack"]]
    detected = sum(row["detected"] for row in attacks)
    fp = sum(row["detected"] for row in benign)
    latencies = [row["time_to_detect"] for row in attacks if row["detected"]]
    profiles = []
    for profile in PROFILES:
        group = [row for row in rows if row["profile"] == profile]
        times = [row["time_to_detect"] for row in group if row["detected"]]
        profiles.append(
            {
                "profile": profile,
                "attack": profile in ATTACKS,
                "sessions": len(group),
                "flagged": sum(row["detected"] for row in group),
                "median_detection_seconds": (
                    round(statistics.median(times), 3) if times else None
                ),
            }
        )
    return {
        "threshold": threshold,
        "attack_sessions": len(attacks),
        "benign_sessions": len(benign),
        "detected_attacks": detected,
        "false_positives": fp,
        "detection_rate": round(detected / len(attacks), 4),
        "false_positive_rate": round(fp / len(benign), 4),
        "detection_ci95": wilson(detected, len(attacks)),
        "false_positive_ci95": wilson(fp, len(benign)),
        "median_detection_seconds": (
            round(statistics.median(latencies), 3) if latencies else None
        ),
        "p95_detection_seconds": (
            round(float(np.percentile(latencies, 95)), 3) if latencies else None
        ),
        "profiles": profiles,
        "sessions": rows,
    }


def evaluate(output=ROOT / "reports", write_policy=True):
    model = SentimentModel()
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    print("Calibrating on 84 synthetic sessions (seeds 100-111)...", flush=True)
    calibration_traces = [
        trace_session(model, p, seed, "calibration", policy)
        for p in PROFILES
        for seed in CALIBRATION_SEEDS
    ]
    candidates = [summarize(calibration_traces, threshold) for threshold in CANDIDATES]

    # Preregistered objective: FP <= 5%, maximize detection, then minimize
    # median latency; ties prefer a larger threshold to reduce sensitivity.
    def objective(result):
        return (
            result["false_positive_rate"] <= 0.05,
            result["detection_rate"] - result["false_positive_rate"],
            -(result["median_detection_seconds"] or 999),
            result["threshold"],
        )

    selected = max(candidates, key=objective)
    policy["throttle_threshold"] = selected["threshold"]
    policy["provenance"] = (
        "Throttle threshold chosen on 84 calibration sessions, seeds 100-111; weights fixed before held-out evaluation."
    )
    policy_json = json.dumps(policy, indent=2) + "\n"
    if write_policy:
        POLICY_PATH.write_text(policy_json, encoding="utf-8", newline="\n")
    print(
        f"Frozen throttle threshold: {selected['threshold']}. Evaluating 210 regression sessions (seeds 10000-10029)...",
        flush=True,
    )
    test_traces = [
        trace_session(model, p, seed, "holdout", policy)
        for p in PROFILES
        for seed in TEST_SEEDS
    ]
    result = summarize(test_traces, selected["threshold"])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "calibration_seed_range": [100, 111],
        "test_seed_range": [10000, 10029],
        "model": model.metadata(),
        "policy": policy,
        "policy_sha256": hashlib.sha256(policy_json.encode()).hexdigest(),
        "calibration": {
            "selected_threshold": selected["threshold"],
            "candidates": [
                {k: v for k, v in c.items() if k not in {"sessions", "profiles"}}
                for c in candidates
            ],
        },
        "test": result,
        "methodology": "Replay 45-second sessions on a virtual clock using the production detector in observe mode. Detection is any score at or above the frozen throttle threshold. The 25/15/35/25 signal weights are fixed; only the throttle threshold is selected on calibration traffic. Final test seeds and subject words are disjoint from calibration and the development pilot (seeds 1000-1019), which revealed invalid boundary probes. Final test labels never enter the detector. A campaign is one attack session, not three independent sessions. Detection timing is simulated arrival time, not a hardware latency measurement.",
        "limitations": [
            "Synthetic traffic is narrower than real-world API behavior; shared generator families can overestimate generalization.",
            "Low-and-slow attacks may take longer than the ten-second demonstration target or evade detection.",
            "The local sentiment model is trained on original synthetic examples; its probabilities are not calibrated on real customer data.",
            "Cross-key correlation requires overlapping normalized inputs and can miss non-overlapping campaigns or flag similar benign automation.",
            "In-memory windows and penalties reset on server restart; SQLite audit records persist. This single-process prototype is not a distributed production gateway.",
        ],
    }
    report["evaluation_kind"] = "regression"
    report["methodology"] += " " + REGRESSION_NOTE
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    table = "\n".join(
        f"| {p['profile']} | {'Attack' if p['attack'] else 'Benign'} | {p['sessions']} | {p['flagged']} | {p['median_detection_seconds'] if p['median_detection_seconds'] is not None else '-'} |"
        for p in result["profiles"]
    )
    (output / "RESULTS.md").write_text(
        f"# ModelShield measured validation\n\nGenerated {report['generated_at']}. Synthetic benchmark only.\n\n- Detection: {result['detected_attacks']}/{result['attack_sessions']} ({result['detection_rate']:.1%}).\n- False positives: {result['false_positives']}/{result['benign_sessions']} ({result['false_positive_rate']:.1%}).\n- Median detection: {result['median_detection_seconds']} seconds; P95: {result['p95_detection_seconds']} seconds (detected attacks only).\n- Frozen throttle threshold: {selected['threshold']}.\n\n| Profile | Truth | Sessions | Flagged | Median detection (s) |\n|---|---|---:|---:|---:|\n{table}\n\n{report['methodology']}\n\n"
        + "\n\n".join(report["limitations"])
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "detection_rate",
                    "false_positive_rate",
                    "median_detection_seconds",
                    "p95_detection_seconds",
                    "profiles",
                ]
            },
            indent=2,
        ),
        flush=True,
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports")
    parser.add_argument("--no-write-policy", action="store_true")
    args = parser.parse_args()
    evaluate(args.output, not args.no_write_policy)
