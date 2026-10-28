"""Request-side heuristics for chat; independent of classifier benchmark policy."""

from collections import deque
from dataclasses import dataclass, field
import hashlib
import math
import re

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

POLICY = {
    "version": "chat-heuristics-v2",
    "window_seconds": 60,
    "monitor_threshold": 35,
    "throttle_threshold": 60,
    "block_threshold": 80,
    "throttle_seconds": 5,
    "block_seconds": 30,
    "speed_bumps": [
        {"threshold": 40, "seconds": 1},
        {"threshold": 50, "seconds": 3},
    ],
    "bulk_pass": {
        "max_requests": 30, "max_minutes": 60, "max_concurrency": 2,
        "repetition_override": 0.65,
        "scope": "Approved arrivals receive rate credit. At least 8 recent inputs and repetition >= 0.65 remove that credit. Diversity and repetition still count.",
    },
    "weights": {"rate": 45, "diversity": 20, "repetition": 35},
    "scope": "Request-side heuristics; not validated by the classifier benchmarks.",
}


@dataclass
class ChatClient:
    queries: deque = field(default_factory=lambda: deque(maxlen=256))
    risk: float = 0
    signals: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    until: float = 0
    action: str = "allow"
    total: int = 0
    answered: int = 0
    denied: int = 0
    errors: int = 0
    last_seen: float = 0
    last_alert: float = float("-inf")
    raw_risk: float = 0
    rate_credit: float = 0
    delayed: int = 0
    waiting: int = 0
    delay_ms: float = 0


class ChatRiskEngine:
    def __init__(self, names):
        self.names = names
        self.clients = {key: ChatClient() for key in names}
        self.vectorizer = HashingVectorizer(
            n_features=2048,
            alternate_sign=False,
            ngram_range=(3, 5),
            analyzer="char_wb",
        )

    def score(self, state, now):
        while state.queries and state.queries[0][0] <= now - 60:
            state.queries.popleft()
        recent = list(state.queries)[-32:]
        n = len(recent)
        count = sum(query[0] > now - 10 for query in state.queries)
        approved = sum(query[0] > now - 10 and query[3] for query in state.queries)
        rate = min(1, max(0, (count - 4) / 12))
        diversity = repetition = 0.0
        if n >= 2:
            vectors = np.vstack([query[2] for query in recent])
            similarities = np.clip(vectors @ vectors.T, 0, 1)
            diversity = float(np.mean(1 - similarities[np.triu_indices(n, 1)]))
            exact = 1 - len({query[1] for query in recent}) / n
            neighbors = float(np.mean(np.diag(similarities, k=1) >= 0.80))
            repetition = max(exact, neighbors)
        evidence = min(1, n / 8)
        # Variation alone must not flag an ordinary wide-ranging conversation.
        activity = min(1, count / 8)
        contributions = {
            "rate": 45 * rate,
            "diversity": 20 * diversity * activity * evidence,
            "repetition": 35 * repetition * activity * evidence,
        }
        state.raw_risk = round(sum(contributions.values()), 1)
        state.rate_credit = 0
        if not (n >= 8 and repetition >= POLICY["bulk_pass"]["repetition_override"]):
            state.rate_credit = contributions["rate"] * approved / max(1, count)
            contributions["rate"] -= state.rate_credit
        state.rate_credit = round(state.rate_credit, 1)
        state.risk = round(sum(contributions.values()), 1)
        state.signals = {
            "rate": {
                "value": count,
                "unit": "requests / 10 s",
                "points": round(contributions["rate"], 1),
            },
            "diversity": {
                "value": round(diversity, 3),
                "unit": "mean lexical distance",
                "points": round(contributions["diversity"], 1),
            },
            "repetition": {
                "value": round(repetition, 3),
                "unit": "duplicate or near-neighbor share",
                "points": round(contributions["repetition"], 1),
            },
        }
        descriptions = {
            "rate": f"{count} requests arrived in 10 seconds",
            "diversity": "Inputs cover unusually different wording in a short burst",
            "repetition": "Repeated or closely varied inputs suggest systematic probing",
        }
        state.reasons = [
            descriptions[name] for name, points in contributions.items() if points >= 10
        ]
        if state.rate_credit:
            state.reasons.append(f"Operator-approved arrivals remove {state.rate_credit} rate points; other signals remain active")
        elif approved and n >= 8 and repetition >= POLICY["bulk_pass"]["repetition_override"]:
            state.reasons.append("Strong repeated probing removes the bulk rate allowance")

    def observe(self, key, text, now, *, approved=False):
        state = self.clients[key]
        normalized = re.sub(r"\s+", " ", text.casefold()).strip()
        fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
        vector = self.vectorizer.transform([normalized]).toarray()[0]
        state.queries.append((now, fingerprint, vector, approved))
        state.total += 1
        state.last_seen = now
        self.score(state, now)
        # A continued burst can escalate an existing throttle to a temporary block.
        if state.risk >= 80 and (state.action != "block" or state.until <= now):
            state.action, state.until = "block", now + 30
        elif state.risk >= 60 and state.until <= now:
            state.action, state.until = "throttle", now + 5
        return self.gate(key, now)

    def delay_seconds(self, key, now):
        state = self.clients[key]
        self.score(state, now)
        return max((row["seconds"] for row in POLICY["speed_bumps"]
                    if state.risk >= row["threshold"]), default=0)

    def gate(self, key, now):
        state = self.clients[key]
        if state.until > now:
            return state.action, max(1, math.ceil(state.until - now))
        return "allow", 0

    def view(self, now):
        rows = []
        for key, state in self.clients.items():
            self.score(state, now)
            action, retry = self.gate(key, now)
            rows.append(
                {
                    "id": key,
                    "name": self.names[key],
                    "risk": state.risk,
                    "raw_risk": state.raw_risk,
                    "rate_credit": state.rate_credit,
                    "speed_bump_seconds": self.delay_seconds(key, now),
                    "waiting": state.waiting,
                    "delayed": state.delayed,
                    "delay_ms": round(state.delay_ms, 1),
                    "status": (
                        action
                        if action != "allow"
                        else "delay" if state.risk >= 40 else "watch" if state.risk >= 35 else "normal"
                    ),
                    "retry_after": retry,
                    "total": state.total,
                    "answered": state.answered,
                    "denied": state.denied,
                    "errors": state.errors,
                    "last_seen": state.last_seen,
                    "signals": state.signals,
                    "reasons": state.reasons,
                }
            )
        return rows
