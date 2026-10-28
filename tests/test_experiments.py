import ast
import json
from pathlib import Path

import httpx
import pytest

from scripts import extract_demo
from scripts.challenge_traffic import challenge
from scripts.compare_defenses import choose, load_external, replay
from scripts.copy_experiment import pools
from modelshield.engine import POLICY_PATH
from modelshield.model import SentimentModel


def test_copy_client_only_collects_released_prediction_labels(monkeypatch):
    original = httpx.Client
    seen = []

    def respond(request):
        assert request.url.path == "/predict"
        assert request.headers["X-API-Key"] == "test-key"
        assert "authorization" not in request.headers
        seen.append(json.loads(request.content))
        if len(seen) == 2:
            return httpx.Response(
                429, headers={"Retry-After": "2"}, json={"action": "throttled"}
            )
        return httpx.Response(200, json={"label": "positive", "confidence": 0.9})

    monkeypatch.setattr(
        extract_demo.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = extract_demo.collect(
        "http://127.0.0.1:12345", "test-key", ["one", "two", "three"], interval=0
    )
    assert seen == [{"text": "one"}, {"text": "two"}, {"text": "three"}]
    assert result["attempted"] == 3 and result["released"] == 2
    assert result["released_before_first_denial"] == 1
    assert result["pairs"] == [
        {"text": "one", "label": "positive"},
        {"text": "three", "label": "positive"},
    ]
    assert extract_demo.train_copy(result["pairs"]) is None
    tree = ast.parse(Path(extract_demo.__file__).read_text(encoding="utf-8"))
    assert all(
        not (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("modelshield")
        )
        for node in ast.walk(tree)
    )


def test_patient_copy_waits_and_retries_same_input(monkeypatch):
    original = httpx.Client
    seen, sleeps = [], []

    def respond(request):
        seen.append(json.loads(request.content)["text"])
        return (
            httpx.Response(429, headers={"Retry-After": "2"}, json={})
            if len(seen) == 1
            else httpx.Response(200, json={"label": "negative"})
        )

    monkeypatch.setattr(
        extract_demo.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(extract_demo.time, "sleep", sleeps.append)
    result = extract_demo.collect(
        "http://127.0.0.1:12345", "key", ["one"], attempts=2, respect_retry=True
    )
    assert seen == ["one", "one"] and sleeps[0] == 2
    assert result["released"] == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://localhost:8000",
        "http://127.0.0.1.evil.test",
        "http://user@127.0.0.1",
        "http://127.0.0.1/admin",
    ],
)
def test_copy_client_is_limited_to_owned_loopback_urls(url):
    with pytest.raises(ValueError):
        extract_demo.local_url(url)


def test_copy_training_and_evaluation_inputs_are_disjoint():
    candidates, tests = pools()
    assert candidates == pools()[0]
    assert not set(candidates).intersection(tests)
    assert len(tests) == 90
    assert (
        extract_demo.train_copy(
            [{"text": str(i), "label": "positive"} for i in range(12)]
        )
        is None
    )


def test_baseline_has_its_own_effective_capacity():
    model = SentimentModel()
    policy = json.loads(POLICY_PATH.read_text())
    scenario = challenge("legitimate_batch", 31000, "challenge")
    result = replay(model, scenario, "rate_only", 5, policy)
    assert result["flagged"] and result["allowed"] == 5
    assert not replay(model, scenario, "disabled", None, policy)["flagged"]


def test_baseline_selection_rejects_high_false_positive_candidate():
    candidates = [
        {
            "setting": 5,
            "detection_rate": 1,
            "false_positive_rate": 0.2,
            "median_detection_seconds": 1,
        },
        {
            "setting": 160,
            "detection_rate": 0.4,
            "false_positive_rate": 0,
            "median_detection_seconds": 20,
        },
    ]
    assert choose(candidates)["setting"] == 160


def test_external_scenario_validation_and_truth_separation(tmp_path):
    scenario = challenge("slow_confident", 1, "challenge")
    assert all(set(q) == {"at", "key", "text"} for q in scenario["queries"])
    path = tmp_path / "challenge.jsonl"
    path.write_text(json.dumps(scenario) + "\n")
    assert load_external(path) == [scenario]
    scenario["queries"][0]["at"] = float("nan")
    path.write_text(json.dumps(scenario) + "\n")
    with pytest.raises(ValueError):
        load_external(path)
