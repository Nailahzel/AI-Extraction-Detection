import json

from fastapi.testclient import TestClient
import pytest

from modelshield.api import create_app
from modelshield.config import ROOT, Settings
from modelshield import requirements


@pytest.fixture
def client(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    for name in requirements.REPORT_FILES.values():
        source = ROOT / "reports" / name
        if source.exists():
            (reports / name).write_bytes(source.read_bytes())
    monkeypatch.setattr(requirements, "REPORTS_DIR", reports)
    app = create_app(
        Settings(data_dir=tmp_path / "data", admin_token="private-operator-test-token")
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as result:
        yield result


def evidence(client):
    client.get("/dashboard")
    response = client.get("/api/requirements")
    assert response.status_code == 200
    return response.json()


def test_jury_evidence_requires_operator_authentication(client):
    for path in [
        "/api/requirements",
        "/api/requirements?download=true",
        "/api/requirements/reports/chat-quality",
    ]:
        assert client.get(path).status_code == 401
    result = evidence(client)
    assert result["implemented_count"] == 5
    assert {item["id"] for item in result["requirements"]} == {
        "inference",
        "traffic",
        "signals",
        "alerts",
        "quality",
    }
    assert "private-operator-test-token" not in json.dumps(result)
    assert "events" not in result


def test_quality_counts_scopes_and_rates_are_not_mixed(client):
    data = evidence(client)
    reports = {report["id"]: report for report in data["quality"]}
    chat = reports["chat-quality"]
    assert chat["model_scope"] == "chat"
    assert chat["detected_attacks"] == 24
    assert chat["attack_sessions"] == 36
    assert chat["false_positive_rate"] == 0.5
    assert chat["detection_rate"] == pytest.approx(2 / 3)
    assert "No language-model generation" in chat["scope"]
    assert reports["classifier-challenges"]["detection_rate"] == 0.4
    assert "Previously inspected" in reports["classifier-regression"]["scope"]


def test_missing_reports_do_not_show_a_completed_measurement(client):
    for name in requirements.REPORT_FILES.values():
        path = requirements.REPORTS_DIR / name
        if path.exists():
            path.unlink()
    data = evidence(client)
    assert data["implemented_count"] == 4
    assert not next(row for row in data["requirements"] if row["id"] == "quality")[
        "implemented"
    ]
    assert all(not report["available"] for report in data["quality"])
    assert not data["demo"]["available"]
    assert client.get("/api/requirements/reports/chat-quality").status_code == 404


@pytest.mark.parametrize("contents", ['{"detection_rate":NaN}', '{"broken":', "[]"])
def test_unreadable_report_is_visible_as_unavailable(client, contents):
    (requirements.REPORTS_DIR / "chat-evaluation.json").write_text(
        contents, encoding="utf-8"
    )
    result = next(
        row for row in evidence(client)["quality"] if row["id"] == "chat-quality"
    )
    assert result["available"] is False
    assert "detection_rate" not in result


def test_inconsistent_percentages_are_not_presented_as_valid_results(client):
    path = requirements.REPORTS_DIR / "chat-evaluation.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["detection_rate"] = 1.0
    path.write_text(json.dumps(report), encoding="utf-8")
    result = next(
        row for row in evidence(client)["quality"] if row["id"] == "chat-quality"
    )
    assert not result["available"]


def test_saved_policy_mismatch_is_disclosed(client):
    path = requirements.REPORTS_DIR / "chat-evaluation.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["policy"]["block_threshold"] = 95
    path.write_text(json.dumps(report), encoding="utf-8")
    result = next(
        row for row in evidence(client)["quality"] if row["id"] == "chat-quality"
    )
    assert result["available"]
    assert result["configuration_matches"] is False


def test_only_allowlisted_evidence_is_downloadable(client):
    evidence(client)
    response = client.get("/api/requirements?download=true")
    assert (
        "modelshield-requirements-evidence.json"
        in response.headers["content-disposition"]
    )
    assert response.headers["cache-control"] == "no-store"
    response = client.get("/api/requirements/reports/chat-quality")
    assert response.json()["false_positive_rate"] == 0.5
    assert "chat-evaluation.json" in response.headers["content-disposition"]
    assert client.get("/api/requirements/reports/secret-env").status_code == 404
    assert client.get("/api/requirements/reports/..%2F..%2F.env").status_code == 404


def test_evidence_api_is_read_only(client):
    evidence(client)
    before = client.get("/api/chat/snapshot").json()["totals"]
    for _ in range(3):
        client.get("/api/requirements")
    after = client.get("/api/chat/snapshot").json()["totals"]
    assert before == after
    page = client.get("/dashboard").text
    assert 'id="requirements-view"' not in page
    assert 'id="batch-questions"' not in page
    assert client.post("/api/requirements").status_code == 405
