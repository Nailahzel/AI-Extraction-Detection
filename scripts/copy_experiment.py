"""Run fair copying comparisons over real local HTTP, with an evaluator-only test set."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import tempfile
import time

import httpx
import joblib

from modelshield.config import ROOT
from scripts.extract_demo import collect, train_copy
from scripts.experiment_support import (
    admin_post,
    fingerprint,
    latency_summary,
    local_server,
)


def pools(seed=7319):
    # New authored templates; these are not imported from the victim's corpus.
    subjects = ["headset", "backpack", "printer", "bicycle", "speaker", "workshop"]
    positive = ["good", "excellent", "wonderful", "reliable", "great"]
    negative = ["bad", "terrible", "awful", "poor", "disappointing"]
    candidates = []
    for subject in subjects:
        for i in range(5):
            candidates.extend(
                [
                    f"After trying the {subject}, I found it {positive[i]}.",
                    f"After trying the {subject}, I found it {negative[i]}.",
                    f"The {subject} feels {positive[i]} yet {negative[i]}.",
                    f"Would this {subject} be {negative[i]} or {positive[i]} for daily use?",
                ]
            )
    rng = random.Random(seed)
    # Freeze ordering before any responses are collected.
    rng.shuffle(candidates)
    tests = [
        f"My assessment of the {subject} after a week: {word}."
        for subject in [
            "telescope",
            "ferry",
            "suitcase",
            "violin",
            "microwave",
            "campsite",
        ]
        for word in positive + negative
    ]
    tests += [
        f"For me, the {subject} has {positive[i]} aspects and {negative[i]} aspects."
        for subject in [
            "telescope",
            "ferry",
            "suitcase",
            "violin",
            "microwave",
            "campsite",
        ]
        for i in range(5)
    ]
    assert not set(candidates) & set(tests)
    return candidates, tests


def customers(url, seconds, started):
    records = []
    sentences = [
        "I enjoyed the excellent service.",
        "My order was terrible.",
        "The product was wonderful.",
        "This delivery was disappointing.",
    ]
    with httpx.Client(base_url=url, trust_env=False, timeout=10) as client:
        for i in range(max(1, int(seconds / 0.5))):
            wait = started + i * 0.5 - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            at = time.perf_counter()
            response = client.post(
                "/predict",
                headers={"X-API-Key": "normal-01"},
                json={"text": sentences[i % len(sentences)]},
            )
            records.append(
                {
                    "at_seconds": at - started,
                    "status": response.status_code,
                    "latency_ms": (time.perf_counter() - at) * 1000,
                }
            )
    return records


def run(output=ROOT / "reports", seed=7319, seconds=8, attempts=120):
    candidates, tests = pools(seed)
    output.mkdir(parents=True, exist_ok=True)
    protocol = {
        "version": 1,
        "seed": seed,
        "attempt_budget": attempts,
        "time_budget_seconds": seconds,
        "candidate_sha256": fingerprint(candidates),
        "test_sha256": fingerprint(tests),
        "test_count": len(tests),
        "copy_algorithm": "character 3–5 gram TF-IDF + logistic regression, C=2",
        "selection": "fixed shuffled pool; label-only collection; no confidence-based acquisition",
        "test_origin": "new locally authored synthetic templates, not an independent teammate dataset",
        "variants": ["unprotected", "protected", "protected_retry_after"],
    }
    # Written before collecting answers or evaluating a copy.
    (output / "copy-protocol.json").write_text(
        json.dumps(protocol, indent=2) + "\n", encoding="utf-8"
    )
    runs = []
    with tempfile.TemporaryDirectory(
        prefix="modelshield-copy-"
    ) as directory, local_server(directory) as (url, headers):
        with httpx.Client(
            base_url=url, headers=headers, trust_env=False, timeout=15
        ) as admin:
            metadata = admin.get("/api/snapshot").json()
            for name in protocol["variants"]:
                admin_post(admin, "/api/reset")
                admin_post(admin, "/api/mode", {"enforce": name != "unprotected"})
                start_snapshot = admin.get("/api/snapshot").json()
                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    customer_task = pool.submit(customers, url, seconds, started)
                    collection = collect(
                        url,
                        "probe-01",
                        candidates,
                        attempts=attempts,
                        seconds=seconds,
                        respect_retry=name == "protected_retry_after",
                    )
                    customer_records = customer_task.result()
                snapshot = admin.get("/api/snapshot").json()
                alerts = [a for a in snapshot["alerts"] if a["client_id"] == "probe-01"]
                first_alert = min((a["at"] for a in alerts), default=None)
                audit = admin.get("/api/export").json()["events"]
                released_before_alert = sum(
                    e["client_id"] == "probe-01"
                    and e["action"] == "allow"
                    and (first_alert is None or e["at"] < first_alert)
                    for e in audit
                )
                copied = train_copy(collection["pairs"], seed)
                artifact_dir = output / "copy-artifacts" / name
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "answers.json").write_text(
                    json.dumps(collection["pairs"], indent=2) + "\n", encoding="utf-8"
                )
                if copied is not None:
                    joblib.dump(copied, artifact_dir / "copy.joblib")
                else:
                    (artifact_dir / "copy.joblib").unlink(missing_ok=True)
                # Test sentences only reach the evaluator after fitting. A separate
                # key under observe mode obtains reference labels via the API.
                admin_post(admin, "/api/reset")
                admin_post(admin, "/api/mode", {"enforce": False})
                reference = collect(
                    url, "normal-02", tests, attempts=len(tests), seconds=30, interval=0
                )
                if len(reference["pairs"]) != len(tests):
                    raise RuntimeError("Reference labeling was incomplete.")
                agreement = None
                matches = None
                if copied is not None:
                    predictions = copied.predict(tests)
                    matches = sum(
                        prediction == pair["label"]
                        for prediction, pair in zip(predictions, reference["pairs"])
                    )
                    agreement = matches / len(tests)
                result = {
                    key: value
                    for key, value in collection.items()
                    if key not in {"pairs", "records"}
                }
                reference_counts = Counter(pair["label"] for pair in reference["pairs"])
                result.update(
                    {
                        "name": name,
                        "training_status": (
                            "trained"
                            if copied is not None
                            else "insufficient training data"
                        ),
                        "training_unique_inputs": len(
                            {p["text"] for p in collection["pairs"]}
                        ),
                        "agreement": agreement,
                        "agreement_matches": matches,
                        "evaluation_inputs": len(tests),
                        "reference_label_counts": dict(reference_counts),
                        "reference_majority_agreement": max(reference_counts.values())
                        / len(tests),
                        "training_label_counts": dict(
                            Counter(pair["label"] for pair in collection["pairs"])
                        ),
                        "first_alert_seconds": (
                            first_alert - start_snapshot["now"] if first_alert else None
                        ),
                        "released_before_first_alert": released_before_alert,
                        "client_latency": latency_summary(collection["records"]),
                        "legitimate": {
                            "attempted": len(customer_records),
                            "allowed": sum(
                                r["status"] == 200 for r in customer_records
                            ),
                            "denied": sum(r["status"] == 429 for r in customer_records),
                            "errors": sum(
                                r["status"] not in {200, 429} for r in customer_records
                            ),
                            "client_latency": latency_summary(customer_records),
                        },
                        "progress": collection["records"],
                        "incidents": alerts,
                    }
                )
                runs.append(result)
                print(
                    f"{name}: {collection['released']}/{collection['attempted']} answers; agreement={agreement}; legitimate={result['legitimate']['allowed']}/{len(customer_records)}",
                    flush=True,
                )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kind": "saved local HTTP copying experiment",
        "protocol": protocol,
        "model": metadata["model"],
        "policy": metadata["policy"],
        "runs": runs,
        "limitations": [
            "One synthetic candidate pool and one seed; not evidence for all models or adaptive attacks.",
            "Agreement measures imitation of victim labels, not task accuracy or percent of a model stolen.",
            "Identical maximum budgets and input ordering; real HTTP scheduling means completed attempt counts can differ.",
            "Retry-After is evaluated under the same time budget; a longer patient attack may recover more answers.",
            "Reference evaluation uses separate input subjects/templates. Data was authored here, not independently collected.",
        ],
    }
    (output / "copy-experiment.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports")
    parser.add_argument("--seed", type=int, default=7319)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--attempts", type=int, default=120)
    args = parser.parse_args()
    run(args.output, args.seed, args.seconds, args.attempts)
