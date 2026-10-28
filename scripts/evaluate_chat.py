"""Reproducible synthetic request-pattern checks, without running or cloning the LLM."""

from collections import defaultdict
import json
import random

from modelshield.chat_engine import ChatRiskEngine, POLICY
from modelshield.config import ROOT

QUESTIONS = [
    "Why is the sky blue?",
    "How do plants turn sunlight into food?",
    "Write a friendly birthday greeting.",
    "What makes bread rise?",
    "Explain how a bicycle stays upright.",
    "What does an API do?",
    "Give me a short poem about snow.",
    "How are mountains formed?",
    "Suggest a title for a space adventure.",
    "Why do magnets attract iron?",
    "How can I organize my study notes?",
    "What is the difference between RAM and storage?",
    "Describe a simple breakfast recipe.",
    "Why do seasons change?",
    "What is a prime number?",
    "Help me introduce a presentation.",
    "Explain what a database index does.",
    "How do whales communicate?",
    "Give me an example of a metaphor.",
    "How does a compass work?",
    "What is the water cycle?",
    "Describe the rules of chess.",
    "How do solar panels work?",
    "Write a polite thank-you message.",
    "Why do soap bubbles look colorful?",
    "What is an algorithm?",
    "Explain how sound travels.",
    "What happens during a lunar eclipse?",
    "How can I plan a small vegetable garden?",
    "What does encryption mean?",
]


def main():
    rows = []
    profiles = {
        "normal_conversation": (False, 5.0, False),
        "legitimate_bulk_questions": (False, 0.025, False),
        "repeated_extraction_probes": (True, 0.025, True),
        "diverse_extraction_queries": (True, 0.025, False),
        "slow_extraction_probes": (True, 5.0, True),
    }
    for seed in range(700, 712):
        for name, (attack, spacing, repeated) in profiles.items():
            rng = random.Random(seed)
            questions = list(QUESTIONS)
            rng.shuffle(questions)
            if repeated:
                questions = [
                    f"Explain how a neural network learns from examples. Keep answer {i + 1} to one sentence."
                    for i in range(30)
                ]
            engine = ChatRiskEngine({"client": "Synthetic client"})
            first, withheld = None, 0
            for index, question in enumerate(questions):
                at = 1000 + index * spacing
                action, _ = engine.observe("client", question, at)
                if action != "allow":
                    withheld += 1
                    if first is None:
                        first = round(at - 1000, 3)
            rows.append(
                {
                    "seed": seed,
                    "profile": name,
                    "attack": attack,
                    "detected": first is not None,
                    "first_restriction_seconds": first,
                    "requests": 30,
                    "withheld_by_arrival_policy": withheld,
                }
            )
    attacks = [row for row in rows if row["attack"]]
    benign = [row for row in rows if not row["attack"]]
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["profile"]].append(row)
    report = {
        "scope": "Standard access without bulk passes. Synthetic development scenarios with virtual arrival times. Detection means throttle/block, not a speed bump. No actual waiting, LLM generation, independent holdout, or cloning-success measurement.",
        "policy": POLICY,
        "sessions": len(rows),
        "attack_sessions": len(attacks),
        "detected_attacks": sum(row["detected"] for row in attacks),
        "benign_sessions": len(benign),
        "false_positives": sum(row["detected"] for row in benign),
        "detection_rate": sum(row["detected"] for row in attacks) / len(attacks),
        "false_positive_rate": sum(row["detected"] for row in benign) / len(benign),
        "profiles": {
            name: {
                "sessions": len(group),
                "flagged": sum(row["detected"] for row in group),
            }
            for name, group in grouped.items()
        },
        "limitations": [
            "A legitimate bulk request and an extraction burst can have identical observable inputs and timing; this detector cannot infer their intent.",
            "Slow extraction can evade the request-rate component.",
            "The policy was designed on similar patterns; these are reproducibility checks, not independent accuracy estimates.",
            "Earlier classifier measurements do not establish protection for the chat language model.",
            "This baseline does not simulate server-side pacing or trusted bulk approvals. See protection-check.json for separate real-model integration scenarios; those are not an accuracy benchmark.",
        ],
        "results": rows,
    }
    path = ROOT / "reports/chat-evaluation.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "results"}, indent=2
        )
    )


if __name__ == "__main__":
    main()
