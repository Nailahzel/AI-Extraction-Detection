"""Seeded local traffic; calibration/test vocabulary and seeds are disjoint."""

from dataclasses import dataclass
import random


@dataclass(frozen=True)
class Query:
    at: float
    key: str
    text: str


VOCAB = {
    "demo": [
        "movie",
        "hotel",
        "camera",
        "delivery",
        "meal",
        "course",
        "application",
        "book",
    ],
    "calibration": [
        "keyboard",
        "restaurant",
        "ticket",
        "headphones",
        "subscription",
        "printer",
        "concert",
        "luggage",
    ],
    "test": [
        "bicycle",
        "workshop",
        "headset",
        "apartment",
        "backpack",
        "cruise",
        "speaker",
        "museum",
    ],
    "holdout": [
        "telescope",
        "ferry",
        "microwave",
        "seminar",
        "campsite",
        "violin",
        "theater",
        "suitcase",
    ],
}


def normal_text(rng, split="demo", varied=False):
    subject = rng.choice(VOCAB[split]) if varied else VOCAB[split][0]
    adjective = rng.choice(
        [
            "excellent",
            "wonderful",
            "great",
            "reliable",
            "terrible",
            "awful",
            "disappointing",
            "poor",
        ]
    )
    template = rng.choice(
        [
            "The {s} was {a}.",
            "I found the {s} really {a}.",
            "What a {a} {s}!",
            "This {s} is absolutely {a}.",
        ]
    )
    return template.format(s=subject, a=adjective)


def probe_text(index, split="demo", style="boundary"):
    subject = VOCAB[split][(index // 6) % len(VOCAB[split])]
    if style == "boundary":
        modifiers = [
            "somewhat",
            "barely",
            "almost",
            "possibly",
            "occasionally",
            "moderately",
        ]
        return (
            f"The {subject} was {modifiers[index % len(modifiers)]} good yet terrible."
        )
    templates = [
        "Considering the {s}, there are aspects on both sides.",
        "Describe an ordinary {s} with no clear preference.",
        "Neither good nor bad: the {s} exists as expected.",
        "The {s} is excellent yet terrible in equal measure.",
        "Would a neutral observer choose this {s} or another one?",
        "An average {s} has tradeoffs, details, and different uses.",
    ]
    return templates[index % len(templates)].format(s=subject)


PROFILES = ["normal", "batch", "neutral", "burst", "boundary", "slow", "distributed"]
ATTACKS = {"burst", "boundary", "slow", "distributed"}


def session(profile, seed=42, split="demo", duration=45):
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    rng, queries, now, index = random.Random(seed), [], 0.0, 0
    while now < duration:
        if profile in {"normal", "batch", "neutral"}:
            key = "batch-01" if profile == "batch" else "normal-01"
            text = normal_text(rng, split, varied=profile == "batch")
            if profile == "neutral":
                text = rng.choice(
                    [
                        f"The {VOCAB[split][0]} arrived on Tuesday.",
                        f"I used the {VOCAB[split][0]} this morning.",
                        f"The {VOCAB[split][0]} is on my desk.",
                    ]
                )
            gap = (
                rng.uniform(0.08, 0.18) if profile == "batch" else rng.uniform(2.5, 5.5)
            )
        elif profile == "distributed":
            key = f"swarm-{index % 3 + 1:02d}"
            text = probe_text(index // 3, split)
            gap = rng.uniform(0.35, 0.55)
        else:
            key = "attacker-01" if profile == "burst" else "probe-01"
            text = probe_text(
                index + seed % 7, split, "broad" if profile == "burst" else "boundary"
            )
            gap = (
                rng.uniform(1.5, 2.4) if profile == "slow" else rng.uniform(0.08, 0.18)
            )
        queries.append(Query(round(now, 4), key, text))
        now += gap
        index += 1
    return queries


def demo_queries(scenario="guided", seed=42):
    if scenario not in {
        "guided",
        "burst",
        "boundary",
        "distributed",
        "normal",
        "batch",
    }:
        raise ValueError("Unknown demo scenario")
    queries = session("normal", seed, duration=32)
    # A second legitimate tenant proves per-key isolation in every attack demo.
    queries += [
        Query(q.at + 0.6, "normal-02", q.text)
        for q in session("normal", seed + 1, duration=30)
    ]
    if scenario not in {"normal"}:
        profile = "burst" if scenario == "guided" else scenario
        queries += [
            Query(q.at + 5, q.key, q.text)
            for q in session(profile, seed + 2, duration=22)
        ]
    return sorted(queries, key=lambda q: q.at)
