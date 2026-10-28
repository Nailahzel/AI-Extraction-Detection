"""Bounded rolling-window detector with auditable feature contributions."""

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import math
import re

import numpy as np
from scipy.sparse import vstack

POLICY_PATH = Path(__file__).with_name("policy.json")


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


@dataclass
class Observation:
    at: float
    confidence: float
    fingerprint: str
    vector: object


@dataclass
class ClientState:
    client_id: str
    name: str
    events: deque = field(default_factory=lambda: deque(maxlen=256))
    intervals: deque = field(default_factory=lambda: deque(maxlen=64))
    risk: float = 0
    peak_risk: float = 0
    total: int = 0
    denied: int = 0
    answered: int = 0
    blocked_until: float = 0
    throttled_until: float = 0
    last_seen: float = 0
    last_trusted: float = 0
    last_alert: float = -1000000
    reasons: list = field(default_factory=list)
    signals: dict = field(default_factory=dict)
    campaign: str | None = None


class RiskEngine:
    def __init__(self, model, clients, policy=None, correlate=True):
        self.model = model
        self.policy = policy or json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.clients = {key: ClientState(key, name) for key, name in clients.items()}
        self.campaigns = []
        self.correlate = correlate
        self._scored_at = None

    def prune(self, state, now):
        while (
            state.events and state.events[0].at <= now - self.policy["window_seconds"]
        ):
            state.events.popleft()

    def gate(self, client_id, now):
        self._refresh_scores(now)
        return self._penalty(client_id, now)

    def _penalty(self, client_id, now):
        state = self.clients[client_id]
        if state.blocked_until > now:
            return "blocked", max(1, math.ceil(state.blocked_until - now))
        if state.throttled_until > now:
            return "throttled", max(1, math.ceil(state.throttled_until - now))
        return "allow", 0

    def observe(self, client_id, text, confidence, now):
        state = self.clients[client_id]
        self.prune(state, now)
        normalized = " ".join(re.findall(r"[\w]+", text.lower()))
        fingerprint = hashlib.sha256(normalized.encode()).hexdigest()[:20]
        state.events.append(
            Observation(now, confidence, fingerprint, self.model.vector(text))
        )
        state.last_seen = now
        self._scored_at = None
        self._refresh_scores(now)
        if state.risk < self.policy["monitor_threshold"] and confidence >= 0.7:
            if state.last_trusted and 0.1 <= now - state.last_trusted <= 60:
                state.intervals.append(now - state.last_trusted)
            state.last_trusted = now
        state.peak_risk = max(state.peak_risk, state.risk)
        return self.view(client_id, now)

    def _score(self, state, now):
        self.prune(state, now)
        events = list(state.events)
        count = len(events)
        if not count:
            state.risk, state.signals, state.reasons, state.campaign = 0, {}, [], None
            return
        baseline = 36.0
        if len(state.intervals) >= 16:
            baseline = clamp(60 / max(float(np.median(state.intervals)), 0.1), 12, 120)
        burst = sum(event.at > now - 10 for event in events) * 6
        sample = events[-48:]
        matrix = vstack([e.vector for e in sample])
        similarities = (matrix @ matrix.T).toarray()
        # Compare each pair once, excluding each input's similarity to itself.
        diversity = (
            float(1 - np.mean(similarities[np.triu_indices(len(sample), 1)]))
            if len(sample) > 1
            else 0
        )
        boundary = sum(e.confidence < 0.65 for e in events) / count
        sequence = sum(
            bool(
                0.48 <= similarities[i - 1, i] < 0.985
                and sample[i - 1].fingerprint != sample[i].fingerprint
            )
            for i in range(1, len(sample))
        ) / max(1, len(sample) - 1)
        normalized_signals = {
            "rate": clamp((burst / baseline - 1) / 3),
            "diversity": clamp((diversity - 0.35) / 0.5),
            "boundary": clamp((boundary - 0.1) / 0.65),
            "sequence": clamp(sequence / 0.65),
        }
        # A small window contributes gradually; eight observations is not a gate.
        evidence_weight = min(1, count / self.policy["minimum_evidence"])
        weighted_score = sum(
            normalized_signals[signal] * weight * 100
            for signal, weight in self.policy["weights"].items()
        )
        state.risk = round(float(weighted_score * evidence_weight), 1)
        state.campaign = None
        state.signals = {
            "rate": count,
            "burst_rpm": burst,
            "baseline_rpm": round(baseline, 1),
            "baseline_ready": len(state.intervals) >= 16,
            "diversity": round(diversity, 3),
            "boundary": round(boundary, 3),
            "sequence": round(sequence, 3),
            "evidence": count,
            "contributions": {
                signal: round(
                    value * self.policy["weights"][signal] * 100 * evidence_weight, 1
                )
                for signal, value in normalized_signals.items()
            },
        }
        reasons = []
        if normalized_signals["rate"] > 0.35:
            reasons.append(
                f"10-second burst is {burst / baseline:.1f}x the {'learned' if len(state.intervals) >= 16 else 'starter'} baseline ({burst}/min equivalent)."
            )
        if normalized_signals["diversity"] > 0.45:
            reasons.append(
                f"Broad input coverage: {diversity:.0%} average lexical distance."
            )
        if normalized_signals["boundary"] > 0.4:
            reasons.append(
                f"{boundary:.0%} of answers are near the decision boundary (confidence below 65%)."
            )
        if normalized_signals["sequence"] > 0.45:
            reasons.append(
                f"{sequence:.0%} of consecutive queries are controlled near-neighbor changes."
            )
        state.reasons = reasons or [
            "Behavior remains within the current observation policy."
        ]

    def _campaigns(self, now):
        # Exact normalized content overlap is deliberate: similarity alone is weak
        # evidence of coordination. No IP addresses or raw prompts are retained.
        active = []
        for state in self.clients.values():
            self.prune(state, now)
            if len(state.events) >= 4:
                active.append(state)
        graph = {s.client_id: set() for s in active}
        edges = []
        for i, left in enumerate(active):
            left_set = {e.fingerprint for e in left.events}
            for right in active[i + 1 :]:
                right_set = {e.fingerprint for e in right.events}
                overlap = len(left_set & right_set) / max(
                    1, min(len(left_set), len(right_set))
                )
                if len(left_set & right_set) >= 3 and overlap >= 0.45:
                    graph[left.client_id].add(right.client_id)
                    graph[right.client_id].add(left.client_id)
                    edges.append(
                        {
                            "keys": [left.client_id, right.client_id],
                            "shared_count": len(left_set & right_set),
                            "overlap_fraction": round(overlap, 3),
                            "shared_fingerprints": sorted(left_set & right_set),
                        }
                    )
        campaigns, visited = [], set()
        for root in graph:
            if root in visited:
                continue
            component, pending = set(), [root]
            while pending:
                node = pending.pop()
                if node in component:
                    continue
                component.add(node)
                pending.extend(graph[node] - component)
            visited |= component
            if len(component) < 3:
                continue
            members = [self.clients[key] for key in sorted(component)]
            events = [e for state in members for e in state.events]
            boundary = sum(e.confidence < 0.65 for e in events) / len(events)
            unique = len({e.fingerprint for e in events})
            if len(events) < 15 or unique < 5 or boundary < 0.4:
                continue
            campaign_id = (
                "CMP-"
                + hashlib.sha256("|".join(sorted(component)).encode())
                .hexdigest()[:6]
                .upper()
            )
            score = round(min(88, 65 + boundary * 15 + min(unique, 15) * 0.5), 1)
            campaigns.append(
                {
                    "id": campaign_id,
                    "keys": sorted(component),
                    "risk": score,
                    "queries": len(events),
                    "shared_patterns": unique,
                    "boundary": round(boundary, 3),
                    "links": [edge for edge in edges if set(edge["keys"]) <= component],
                    "reason": "At least 3 keys share multiple normalized probes and repeatedly request uncertain predictions.",
                }
            )
            for state in members:
                state.campaign = campaign_id
                state.risk = max(state.risk, score)
                state.peak_risk = max(state.peak_risk, state.risk)
                reason = f"Coordinated probing across {len(component)} API keys ({campaign_id}); shared input fingerprints and {boundary:.0%} uncertain answers."
                state.reasons = [
                    r for r in state.reasons if not r.startswith("Coordinated probing")
                ]
                state.reasons.append(reason)
        self.campaigns = campaigns

    def enforce(self, client_id, now):
        self._refresh_scores(now)
        state = self.clients[client_id]
        if state.risk >= self.policy["block_threshold"]:
            state.blocked_until = now + self.policy["cooldown_seconds"]
            return "blocked", self.policy["cooldown_seconds"]
        if state.risk >= self.policy["throttle_threshold"]:
            state.throttled_until = now + self.policy["throttle_seconds"]
            return "throttled", self.policy["throttle_seconds"]
        return "allow", 0

    def view(self, client_id, now):
        self._refresh_scores(now)
        state = self.clients[client_id]
        self.prune(state, now)
        if not state.events:
            state.risk, state.signals, state.reasons, state.campaign = 0, {}, [], None
        action, retry = self._penalty(client_id, now)
        status = (
            action
            if action != "allow"
            else (
                "monitor"
                if state.risk >= self.policy["monitor_threshold"]
                else "healthy"
            )
        )
        return {
            "id": state.client_id,
            "name": state.name,
            "risk": state.risk,
            "peak_risk": state.peak_risk,
            "status": status,
            "retry_after": retry,
            "total": state.total,
            "denied": state.denied,
            "answered": state.answered,
            "last_seen": state.last_seen,
            "signals": state.signals,
            "reasons": state.reasons,
            "campaign": state.campaign,
        }

    def _refresh_scores(self, now):
        if self._scored_at == now:
            return
        for state in self.clients.values():
            # Scores describe current evidence. Incident records preserve history.
            self._score(state, now)
        if self.correlate:
            self._campaigns(now)
        else:
            self.campaigns = []
        self._scored_at = now

    def refresh(self, now):
        self._refresh_scores(now)
        return [self.view(key, now) for key in self.clients]
