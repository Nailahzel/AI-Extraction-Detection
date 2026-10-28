"""New synthetic challenge families; ground truth is evaluator-only metadata.

Authored in this project, not represented as an independent teammate evaluation.
An external evaluator can supply the same session schema without changing rules.
"""

import random

PROFILES = (
    "legitimate_batch",
    "legitimate_ambiguous",
    "legitimate_shared",
    "fast_collector",
    "slow_confident",
    "nonoverlap_keys",
    "patient_collector",
    "overlap_keys",
)
BENIGN = set(PROFILES[:3])


def challenge(profile, seed, split):
    if profile not in PROFILES or split not in {"calibration", "challenge"}:
        raise ValueError("Unknown profile or split.")
    rng = random.Random(seed)
    subjects = (
        ["router", "monitor", "sofa", "kettle", "tablet", "battery"]
        if split == "calibration"
        else ["tent", "piano", "oven", "scooter", "jacket", "drone"]
    )
    ordinary = ["excellent", "awful", "reliable", "poor", "wonderful", "disappointing"]
    mixed = [
        "useful but unreliable",
        "good yet terrible",
        "neither enjoyable nor awful",
        "promising but disappointing",
        "average with some tradeoffs",
        "pleasant despite several problems",
    ]
    rows = []
    count = (
        120
        if profile == "legitimate_batch"
        else (
            180
            if profile in {"fast_collector", "patient_collector"}
            else 18 if profile == "slow_confident" else 60
        )
    )
    for i in range(count):
        key = (
            f"client-{i % 3}"
            if profile in {"legitimate_shared", "nonoverlap_keys", "overlap_keys"}
            else "client-0"
        )
        subject = subjects[(i // 6) % len(subjects)]
        if profile in {"legitimate_batch", "slow_confident"}:
            word = rng.choice(ordinary)
            subject = rng.choice(subjects)
            text = (
                f"We tried the {subject} over the weekend. Our experience was {word}."
            )
        elif profile == "legitimate_ambiguous":
            text = f"Customer note {i}: the {subject} is {mixed[i % len(mixed)]}."
        elif profile == "legitimate_shared":
            text = f"Survey response: our {subjects[(i // 3) % len(subjects)]} was {ordinary[(i // 9) % len(ordinary)]}."
        elif profile == "nonoverlap_keys":
            text = f"For department {key}, assess {subject} option {i}: {mixed[i % len(mixed)]}."
        elif profile == "overlap_keys":
            j = i // 3
            text = (
                f"Is the {subjects[(j // 6) % len(subjects)]} {mixed[j % len(mixed)]}?"
            )
        else:
            text = rng.choice(
                [
                    f"Explain whether {subject} option {i} is good, bad, or neither.",
                    f"Assessment {i}: a {subject} that is {mixed[i % len(mixed)]}.",
                    f"Would you classify {subject} item {i} as excellent or terrible?",
                ]
            )
        gap = (
            2.4
            if profile == "slow_confident"
            else 0.65 if count == 60 else 0.15 if count == 120 else 0.2
        )
        rows.append({"at": round(i * gap, 3), "key": key, "text": text})
    return {
        "profile": profile,
        "seed": seed,
        "attack": profile not in BENIGN,
        "duration": 45,
        "respect_retry_after": profile == "patient_collector",
        "queries": rows,
    }
