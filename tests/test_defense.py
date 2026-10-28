import pytest
from fastapi.testclient import TestClient

from modelshield.api import create_app
from modelshield.config import DEMO_KEYS, Settings
from modelshield.engine import RiskEngine
from modelshield.model import SentimentModel
from modelshield.traffic import demo_queries, session


@pytest.fixture(scope="module")
def model():
    return SentimentModel()


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, admin_token="unit-test-admin-secret"))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        client.get("/")
        yield client


def test_classifier_returns_real_sentiment(model):
    assert model.predict("The service was wonderful.")[0] == "positive"
    assert model.predict("The product was terrible.")[0] == "negative"
    assert model.predict("The product was not good.")[0] == "negative"
    assert 0.5 <= model.predict("Ordinary objects exist.")[1] <= 1


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Absolutely fantastic—another update that crashes every ten minutes and deletes all my work. Exactly what I needed!”",
            "negative",
        ),
        (
            "Wonderful update. It crashes twice an hour and deletes the document I was editing.",
            "negative",
        ),
        (
            "Amazing software: it freezes constantly and loses my work again!",
            "negative",
        ),
        (
            "Great service, it charged me twice and refuses to refund my money.",
            "negative",
        ),
        ("Fantastic update: it saves my work and never crashes.", "positive"),
        (
            "The update is fantastic. It no longer crashes and my documents are safe.",
            "positive",
        ),
        ("Wonderful, the app fixed the crashes and recovered my files!", "positive"),
        (
            "Absolutely fantastic—an update that keeps my work safe and works smoothly. Exactly what I needed!",
            "positive",
        ),
    ],
)
def test_classifier_uses_failure_and_recovery_context(model, text, expected):
    assert model.predict(text)[0] == expected


def test_sarcastic_complaint_is_negative_but_not_an_attack(client):
    text = "Absolutely fantastic—another update that crashes every ten minutes and deletes all my work. Exactly what I needed!”"
    response = client.post(
        "/predict", headers={"X-API-Key": "normal-01"}, json={"text": text}
    )
    assert response.status_code == 200
    assert response.json()["label"] == "negative"
    snapshot = client.get("/api/snapshot").json()
    assert snapshot["totals"]["denied"] == 0
    assert snapshot["alerts"] == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "   "},
        {"text": 12},
        {"text": "a" * 2001},
        {"text": "good", "extra": True},
    ],
)
def test_invalid_payloads_rejected(client, body):
    assert (
        client.post(
            "/predict", headers={"X-API-Key": "normal-01"}, json=body
        ).status_code
        == 422
    )


def test_api_auth_and_admin_boundary(client):
    assert client.post("/predict", json={"text": "good"}).status_code == 401
    assert (
        client.post(
            "/predict", headers={"X-API-Key": "made-up"}, json={"text": "good"}
        ).status_code
        == 401
    )
    client.cookies.clear()
    assert client.get("/api/snapshot").status_code == 401
    assert client.post("/api/reset").status_code == 401
    assert (
        client.get(
            "/api/snapshot", headers={"Authorization": "Bearer unit-test-admin-secret"}
        ).status_code
        == 200
    )


def test_cross_origin_admin_mutation_rejected(client):
    assert (
        client.post(
            "/api/reset", headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    assert client.get("/", headers={"Host": "rebound.example"}).status_code == 400


def test_body_limit(client):
    response = client.post(
        "/predict",
        headers={"X-API-Key": "normal-01", "Content-Type": "application/json"},
        content=b'{"text":"' + b"a" * 20000 + b'"}',
    )
    assert response.status_code == 413


def test_detect_and_isolate_attacker(client):
    statuses = []
    for query in session("burst", 42, duration=8)[:45]:
        response = client.post(
            "/predict", headers={"X-API-Key": query.key}, json={"text": query.text}
        )
        statuses.append(response.status_code)
        if response.status_code == 429:
            assert int(response.headers["Retry-After"]) > 0
            assert "confidence" not in response.json()
            assert "label" not in response.json()
    assert 429 in statuses
    normal = client.post(
        "/predict",
        headers={"X-API-Key": "normal-01"},
        json={"text": "The service was wonderful."},
    )
    assert normal.status_code == 200
    snapshot = client.get("/api/snapshot").json()
    assert snapshot["totals"]["denied"] > 0
    assert any(
        alert["client_id"] == "attacker-01" and len(alert["reasons"]) >= 2
        for alert in snapshot["alerts"]
    )
    assert next(c for c in snapshot["clients"] if c["id"] == "normal-01")["denied"] == 0


@pytest.mark.parametrize("profile", ["normal", "batch", "neutral"])
def test_benign_traffic_is_not_enforced(model, profile):
    engine = RiskEngine(model, DEMO_KEYS)
    for query in session(profile, 1000, "test", duration=35):
        view = engine.observe(
            query.key, query.text, model.predict(query.text)[1], 1000 + query.at
        )
        assert view["risk"] < engine.policy["throttle_threshold"]


def test_campaign_detection_uses_content_not_client_names(model):
    clients = {f"opaque-{i}": "Unlabeled client" for i in range(3)}
    engine = RiskEngine(model, clients)
    for query in session("distributed", 1001, "test", duration=15):
        key = f"opaque-{int(query.key[-1])-1}"
        engine.observe(key, query.text, model.predict(query.text)[1], 1000 + query.at)
    assert len(engine.campaigns) == 1
    assert set(engine.campaigns[0]["keys"]) == set(clients)
    assert all(
        c.risk >= engine.policy["throttle_threshold"] for c in engine.clients.values()
    )


def test_expired_observations_and_penalty_release(model):
    engine = RiskEngine(model, DEMO_KEYS)
    for query in session("burst", 42, duration=5):
        engine.observe(
            query.key, query.text, model.predict(query.text)[1], 1000 + query.at
        )
    engine.enforce("attacker-01", 1005)
    assert engine.gate("attacker-01", 1005)[0] in {"blocked", "throttled"}
    engine.refresh(1100)
    assert engine.gate("attacker-01", 1100) == ("allow", 0)
    assert engine.view("attacker-01", 1100)["risk"] == 0
    assert not engine.clients["attacker-01"].events


def test_observe_mode_and_reset(client):
    assert client.post("/api/mode", json={"enforce": False}).status_code == 200
    for query in session("burst", 42, duration=4)[:30]:
        assert (
            client.post(
                "/predict", headers={"X-API-Key": query.key}, json={"text": query.text}
            ).status_code
            == 200
        )
    snapshot = client.get("/api/snapshot").json()
    assert snapshot["alerts"]
    assert snapshot["totals"]["denied"] == 0
    assert client.post("/api/reset").status_code == 200
    snapshot = client.get("/api/snapshot").json()
    assert snapshot["totals"]["requests"] == 0
    assert not snapshot["events"]
    assert not snapshot["alerts"]


def test_audit_export_has_no_raw_prompt(client):
    text = "The product was wonderful. confidential-customer-note-9842"
    client.post("/predict", headers={"X-API-Key": "normal-01"}, json={"text": text})
    export = client.get("/api/export")
    assert export.status_code == 200
    assert "confidential-customer-note" not in export.text
    assert export.json()["events"][0]["action"] == "allow"


def test_simulation_is_reproducible_and_split_inputs_differ():
    assert demo_queries("guided", 42) == demo_queries("guided", 42)
    assert demo_queries("guided", 42) != demo_queries("guided", 43)
    cal = {q.text for q in session("boundary", 100, "calibration")}
    test = {q.text for q in session("boundary", 1000, "test")}
    assert not cal.intersection(test)


def test_demo_lifecycle_and_unknown_scenario(client):
    assert (
        client.post("/api/demo/start", json={"scenario": "unknown"}).status_code == 422
    )
    assert (
        client.post("/api/demo/start", json={"scenario": "normal"}).status_code == 200
    )
    assert (
        client.post("/api/demo/start", json={"scenario": "normal"}).status_code == 409
    )
    assert client.post("/api/demo/stop").status_code == 200
    assert (
        client.post("/api/demo/start", json={"scenario": "normal"}).status_code == 200
    )
    assert client.post("/api/reset").status_code == 200
    assert not client.get("/api/snapshot").json()["demo"]["running"]


def test_non_demo_requires_explicit_credentials(tmp_path):
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, demo=False, keys={}, admin_token="")
    settings = Settings(
        data_dir=tmp_path,
        demo=False,
        keys={"secret-client-key": "Production client"},
        admin_token="a" * 40,
    )
    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as client:
        client.get("/")
        assert client.get("/api/snapshot").status_code == 401
        headers = {"Authorization": "Bearer " + "a" * 40}
        assert (
            client.post("/api/demo/start", json={}, headers=headers).status_code == 403
        )
        client.post(
            "/predict",
            headers={"X-API-Key": "secret-client-key"},
            json={"text": "A wonderful product"},
        )
        export = client.get("/api/export", headers=headers)
        assert "secret-client-key" not in export.text
        assert client.post("/api/reset", headers=headers).status_code == 403


def test_sqlite_audit_survives_restart(tmp_path):
    settings = Settings(data_dir=tmp_path, admin_token="restart-test-admin")
    with TestClient(create_app(settings)) as client:
        client.post(
            "/predict",
            headers={"X-API-Key": "normal-01"},
            json={"text": "A great product"},
        )
    with TestClient(create_app(settings)) as client:
        snapshot = client.get(
            "/api/snapshot", headers={"Authorization": "Bearer restart-test-admin"}
        ).json()
        assert len(snapshot["events"]) == 1
        assert snapshot["totals"]["requests"] == 0


def test_snapshot_serializes_partial_sequential_signals(client):
    for text in [
        "The movie was good.",
        "The movie was quite good.",
        "An ordinary item arrived today.",
        "The hotel was terrible.",
        "The hotel was quite terrible.",
        "Nothing else to add.",
    ]:
        client.post("/predict", headers={"X-API-Key": "normal-01"}, json={"text": text})
        response = client.get("/api/snapshot")
        assert response.status_code == 200
        assert type(response.json()["totals"]["at_risk"]) is int


def test_baseline_adapts_only_from_trusted_intervals(model):
    engine = RiskEngine(model, DEMO_KEYS)
    for index in range(20):
        engine.observe(
            "normal-01", "The product was wonderful.", 0.94, 1000 + index * 2
        )
    view = engine.view("normal-01", 1038)
    assert view["signals"]["baseline_ready"]
    assert view["signals"]["baseline_rpm"] == 30
    trusted_count = len(engine.clients["normal-01"].intervals)
    engine.observe("normal-01", "An uncertain example.", 0.51, 1039)
    assert len(engine.clients["normal-01"].intervals) == trusted_count


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_is_a_client_error(client, constant):
    response = client.post(
        "/predict",
        content='{"text":' + constant + "}",
        headers={"Content-Type": "application/json", "X-API-Key": "normal-01"},
    )
    assert response.status_code == 422
    assert "input" not in response.json()["detail"][0]
    assert client.get("/health").status_code == 200


def test_non_ascii_admin_token_is_rejected(client):
    response = client.get("/api/snapshot", headers={b"Authorization": b"Bearer \xff"})
    assert response.status_code == 401


def test_campaign_expires_without_dashboard_refresh(model):
    engine = RiskEngine(model, DEMO_KEYS)
    for query in session("distributed", 1001, "test", duration=15):
        engine.observe(
            query.key, query.text, model.predict(query.text)[1], 1000 + query.at
        )
    assert engine.campaigns
    assert engine.gate("swarm-01", 1100) == ("allow", 0)
    assert not engine.campaigns
    assert all(c.risk == 0 and c.campaign is None for c in engine.clients.values())


def test_known_campaign_can_cross_threshold_before_individual_monitoring(model):
    full = RiskEngine(model, DEMO_KEYS)
    individual = RiskEngine(model, DEMO_KEYS, correlate=False)
    found = False
    for query in session("distributed", 42, duration=15):
        confidence = model.predict(query.text)[1]
        group = full.observe(query.key, query.text, confidence, 1000 + query.at)
        single = individual.observe(query.key, query.text, confidence, 1000 + query.at)
        if group["campaign"] and group["risk"] >= 55 and single["risk"] < 55:
            found = True
            break
    assert (
        found
    ), "The known distributed demo should illustrate early cross-key evidence."


def test_incident_ids_do_not_depend_on_bounded_history(client):
    svc = client.app.state.service
    svc.engine.clients["probe-01"].risk = 90
    identifiers = set()
    for i in range(110):
        svc.timeline.clear()
        incident_id = svc.alert("probe-01", 1000 + 11 * i, "blocked")
        assert incident_id and incident_id not in identifiers
        identifiers.add(incident_id)
    assert len(svc.alerts) == 100


def test_audit_retention_is_enforced_across_restarts(tmp_path):
    from modelshield.storage import AuditStore

    path = tmp_path / "audit.sqlite3"
    for i in range(9):
        store = AuditStore(path, retention=3)
        store.record(i, "key", "allow", 0, 1, {})
        assert len(store.export()) <= 3
        store.close()
    store = AuditStore(path, retention=2)
    assert [e["at"] for e in store.export()] == [8, 7]
    store.close()


def test_incident_evidence_survives_later_activity_and_restart(tmp_path):
    from modelshield.traffic import probe_text

    settings = Settings(data_dir=tmp_path, admin_token="incident-test-admin")
    headers = {"Authorization": "Bearer incident-test-admin"}
    with TestClient(create_app(settings)) as client:
        for i in range(15):
            client.post(
                "/predict",
                headers={"X-API-Key": "probe-01"},
                json={"text": probe_text(i)},
            )
        alert = client.get("/api/snapshot", headers=headers).json()["alerts"][0]
        path = "/api/incidents/" + alert["id"]
        record = client.get(path, headers=headers).json()
        assert record["risk"] == alert["risk"]
        assert record["policy"] == alert["policy"]
        assert record["signals"] == alert["signals"]
        assert record["incident_id"] == alert["id"]
        client.app.state.service.engine.policy["throttle_threshold"] = 79
        assert client.get(path, headers=headers).json() == record
        assert client.get(path).status_code == 401
    with TestClient(create_app(settings)) as client:
        assert client.get(path, headers=headers).json() == record
        assert client.get("/api/incidents/missing", headers=headers).status_code == 404
