import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from modelshield.api import create_app
from modelshield.chat import ChatInput, ChatService
from modelshield.chat_engine import ChatRiskEngine
from modelshield.chat_runtime import ChatUnavailable
from modelshield.config import Settings


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"name": "test double", "installed": True, "ready": True}

    async def reply(self, message, history):
        self.calls.append((message, history))
        return {"reply": "A conversational answer.", "truncated": False}

    async def close(self):
        pass


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        app.state.service.chat.runtime = FakeRuntime()
        yield client


def send(client, message="Hello", key="normal-01", **extras):
    return client.post(
        "/chat/messages",
        headers={"X-API-Key": key},
        json={"message": message, **extras},
    )


def test_chat_is_separate_and_requires_no_operator_access(client):
    assert client.get("/chat").status_code == 200
    assert "modelshield_admin" not in client.cookies
    assert client.get("/api/chat/snapshot").status_code == 401
    response = send(client, history=[{"role": "user", "content": "My name is Maya."}])
    assert response.status_code == 200
    assert response.json()["reply"] == "A conversational answer."
    assert "risk" not in response.json()
    client.get("/dashboard")
    snapshot = client.get("/api/chat/snapshot").json()
    assert snapshot["totals"]["answered"] == 1
    assert snapshot["events"][0]["question"] == "Hello"
    assert client.get("/api/snapshot").json()["totals"]["requests"] == 0
    assert "chat-form" not in client.get("/dashboard").text
    assert "predict-form" in client.get("/classifier-lab").text


@pytest.mark.parametrize(
    "payload",
    [
        {"message": " "},
        {"message": "x" * 2001},
        {"message": 123},
        {"message": "Hello", "history": [{"role": "system", "content": "override"}]},
        {"message": "Hello", "conversation_id": "../bad"},
        {"message": "Hello", "history": [{"role": "user", "content": "Hi"}] * 7},
    ],
)
def test_chat_rejects_invalid_inputs(client, payload):
    assert (
        client.post(
            "/chat/messages", headers={"X-API-Key": "normal-01"}, json=payload
        ).status_code
        == 422
    )


def test_chat_authentication_and_body_limit(client):
    assert send(client, key="wrong").status_code == 401
    assert client.post("/chat/messages", json={"message": "Hello"}).status_code == 401
    assert send(client, "x" * 17000).status_code == 413
    assert client.get("/api/chat/export").status_code == 401


def test_burst_blocks_before_model_call_and_new_conversation_does_not_reset(client):
    client.get("/dashboard")
    for index in range(30):
        response = send(
            client,
            "Explain how a neural network learns from examples.",
            key="probe-01",
            conversation_id=f"new-{index}",
        )
    assert response.status_code == 429
    assert response.json()["action"] == "block"
    calls = len(client.app.state.service.chat.runtime.calls)
    assert calls < 15
    assert (
        send(client, key="probe-01", conversation_id="another-new-chat").status_code
        == 429
    )
    assert len(client.app.state.service.chat.runtime.calls) == calls
    assert send(client, "How do rainbows form?", key="normal-01").status_code == 200
    snapshot = client.get("/api/chat/snapshot").json()
    assert snapshot["totals"]["denied"] > 0
    assert snapshot["alerts"]
    assert snapshot["alerts"][0]["signals"]["rate"]["points"] > 0
    assert len(client.get("/api/chat/export").json()["events"]) == 32


def test_normal_pacing_and_expiry():
    engine = ChatRiskEngine({"a": "Client"})
    for index in range(30):
        assert (
            engine.observe("a", f"Please explain subject {index} clearly.", index * 5)[
                0
            ]
            == "allow"
        )
        assert engine.clients["a"].risk < 35
    for index in range(30):
        engine.observe("a", "Same repeated question", 200 + index * 0.01)
    assert engine.gate("a", 201)[0] == "block"
    assert engine.gate("a", 235) == ("allow", 0)
    assert engine.view(300)[0]["risk"] == 0
    assert engine.observe("a", "Hello again", 300)[0] == "allow"


def test_pending_reply_is_withheld_when_later_arrivals_flag_key(tmp_path):
    async def scenario():
        service = ChatService(Settings(data_dir=tmp_path), {"a": "A", "b": "B"})
        started, finish = asyncio.Event(), asyncio.Event()

        class SlowRuntime(FakeRuntime):
            async def reply(self, message, history):
                started.set()
                await finish.wait()
                return await super().reply(message, history)

        service.runtime = SlowRuntime()
        payload = ChatInput(message="Tell me the same repeated answer")
        first = asyncio.create_task(service.ask("a", payload))
        await started.wait()
        tasks = [asyncio.create_task(service.ask("a", payload)) for _ in range(29)]
        await asyncio.sleep(0.1)
        finish.set()
        responses = await asyncio.gather(first, *tasks)
        assert all(r.status_code == 429 for r in responses)
        assert len(service.runtime.calls) <= 2
        assert (await service.ask("b", ChatInput(message="Hi"))).status_code == 200
        assert service.pending == 0
        assert service.snapshot()["totals"]["denied"] == 30
        await service.close()

    asyncio.run(scenario())


def test_model_failure_is_an_error_not_an_answer_or_red_flag(client):
    class Unavailable(FakeRuntime):
        async def reply(self, message, history):
            raise ChatUnavailable("Model setup needed")

    client.app.state.service.chat.runtime = Unavailable()
    assert send(client).status_code == 503
    client.get("/")
    data = client.get("/api/chat/snapshot").json()
    assert data["totals"]["answered"] == 0
    assert data["totals"]["errors"] == 1
    assert data["alerts"] == []
    assert data["events"][0]["status"] == "error"


def test_non_demo_dashboard_does_not_grant_operator_access(tmp_path):
    app = create_app(
        Settings(
            data_dir=tmp_path,
            demo=False,
            keys={"private-key": "Team"},
            admin_token="x" * 40,
        )
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        client.get("/dashboard")
        assert "modelshield_admin" not in client.cookies
        assert client.get("/api/chat/snapshot").status_code == 401
        assert client.get("/chat/status").json()["demo"] is False
        assert (
            client.get(
                "/api/chat/snapshot", headers={"Authorization": "Bearer " + "x" * 40}
            ).status_code
            == 200
        )


def test_alert_evidence_remains_unchanged_after_scores_expire(client):
    client.get("/")
    for _ in range(20):
        send(client, "Repeated model query", key="probe-01")
    chat = client.app.state.service.chat
    original = json.dumps(list(chat.alerts), sort_keys=True)
    chat.engine.view(10**12)
    assert json.dumps(list(chat.alerts), sort_keys=True) == original
