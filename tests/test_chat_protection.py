import asyncio
import json
import time

from fastapi.testclient import TestClient
import pytest

from modelshield.api import create_app
from modelshield.bulk import BulkPassInput
from modelshield.chat import ChatInput, ChatService
from modelshield.chat_engine import ChatRiskEngine
from modelshield.chat_scenarios import QUESTIONS, scenario_questions
from modelshield.config import Settings


class Runtime:
    def __init__(self):
        self.calls = []
        self.active = self.maximum = 0

    def status(self):
        return {"name": "test double", "installed": True, "ready": True}

    async def reply(self, message, history):
        self.calls.append(time.monotonic())
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(0.005)
            return {"reply": "A test answer", "truncated": False}
        finally:
            self.active -= 1

    async def close(self):
        pass


def service(tmp_path):
    result = ChatService(Settings(data_dir=tmp_path), {"a": "A", "b": "B"})
    result.runtime = Runtime()
    return result


def grant(chat, **kwargs):
    return chat.passes.issue(BulkPassInput(client_id="a", purpose="Approved varied questions", **kwargs), time.time())


def test_pass_management_requires_operator_and_same_origin(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path)), client=("127.0.0.1", 50000)) as client:
        body = {"client_id": "batch-01", "purpose": "Customer batch"}
        assert client.post("/api/chat/passes", json=body).status_code == 401
        assert client.post("/api/chat/tests/start", json={"client_id": "probe-01", "scenario": "speed_bump"}).status_code == 401
        assert client.get("/chat/access").status_code == 401
        client.get("/dashboard")
        assert client.post("/api/chat/passes", json=body, headers={"Origin": "https://untrusted.invalid"}).status_code == 403
        for overrides in [{"limit": 31}, {"limit": True}, {"minutes": 0}, {"concurrency": 3}, {"purpose": "   "}, {"approved": True}]:
            assert client.post("/api/chat/passes", json={**body, **overrides}).status_code == 422
        assert client.post("/api/chat/passes", json={**body, "client_id": "unknown"}).status_code == 404
        issued = client.post("/api/chat/passes", json=body).json()
        assert client.post("/api/chat/passes", json=body).status_code == 409
        assert client.get("/chat/access", headers={"X-API-Key": "normal-01"}).json()["bulk_pass"] is None
        assert client.get("/chat/access", headers={"X-API-Key": "batch-01"}).json()["bulk_pass"]["id"] == issued["id"]
        client.cookies.clear()
        assert client.post(f"/api/chat/passes/{issued['id']}/revoke").status_code == 401


def test_approved_volume_is_allowed_but_repetition_overrides_credit():
    for questions, approved, expected in [(QUESTIONS, True, "allow"), (QUESTIONS, False, "throttle"), (scenario_questions("probing"), True, "block")]:
        engine = ChatRiskEngine({"a": "A"})
        for i, question in enumerate(questions):
            action, _ = engine.observe("a", question, 1000 + i * .01, approved=approved)
        assert action == expected
        state = engine.clients["a"]
        if action == "allow":
            assert state.rate_credit == 45
            assert state.risk < 35
        elif approved:
            assert state.rate_credit == 0
            assert any("removes the bulk" in reason for reason in state.reasons)


@pytest.mark.parametrize("concurrency", [1, 2])
def test_concurrent_allowance_consumption_never_overruns_or_skips_queue_limit(tmp_path, concurrency):
    async def run():
        chat = service(tmp_path)
        approved = grant(chat, concurrency=concurrency)
        try:
            responses = await asyncio.gather(*(chat.ask("a", ChatInput(message=question, bulk_pass_id=approved["id"])) for question in QUESTIONS))
            assert all(response.status_code == 200 for response in responses)
            assert chat.runtime.maximum <= concurrency
            assert chat.passes.records[approved["id"]]["used"] == 30
            calls = len(chat.runtime.calls)
            responses = await asyncio.gather(*(chat.ask("a", ChatInput(message=question, bulk_pass_id=approved["id"])) for question in QUESTIONS[:5]))
            assert all(response.status_code == 429 for response in responses)
            assert len(chat.runtime.calls) == calls
            assert chat.passes.records[approved["id"]]["used"] == 30
            assert not chat.active and chat.pending == 0
            assert chat.slots._value == 2
        finally:
            await chat.close()
    asyncio.run(run())


def test_grants_survive_restart_and_cannot_be_used_by_another_key(tmp_path):
    async def run():
        chat = service(tmp_path)
        approved = grant(chat, limit=2)
        payload = ChatInput(message="What does an API do?", bulk_pass_id=approved["id"])
        assert (await chat.ask("b", payload)).status_code == 429
        assert not chat.runtime.calls
        assert chat.passes.records[approved["id"]]["used"] == 0
        assert (await chat.ask("a", payload)).status_code == 200
        await chat.close()
        chat = service(tmp_path)
        assert chat.passes.records[approved["id"]]["used"] == 1
        chat.passes.revoke(approved["id"], time.time())
        await chat.close()
        chat = service(tmp_path)
        assert (await chat.ask("a", payload)).status_code == 429
        assert not chat.runtime.calls
        await chat.close()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["revoke", "expire"])
def test_pending_answers_are_withheld_after_pass_changes(tmp_path, change):
    async def run():
        chat = service(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        class Slow(Runtime):
            async def reply(self, message, history):
                entered.set()
                await release.wait()
                return await super().reply(message, history)
        chat.runtime = Slow()
        approved = grant(chat)
        tasks = [asyncio.create_task(chat.ask("a", ChatInput(message=q, bulk_pass_id=approved["id"]))) for q in QUESTIONS[:4]]
        await entered.wait()
        async with chat.lock:
            if change == "revoke":
                chat.passes.revoke(approved["id"], time.time())
            else:
                chat.passes.save({**chat.passes.records[approved["id"]], "expires_at": time.time() - 1})
        release.set()
        responses = await asyncio.gather(*tasks)
        assert all(response.status_code == 429 for response in responses)
        assert all(json.loads(response.body)["action"] == "bulk_limit" for response in responses)
        assert len(chat.runtime.calls) <= 2
        assert all(row["reply"] is None for row in chat.store.recent())
        assert chat.pending == 0 and chat.slots._value == 2
        await chat.close()
    asyncio.run(run())


def test_speed_bump_is_measured_before_inference_and_other_key_can_proceed(tmp_path):
    async def run():
        chat = service(tmp_path)
        responses = asyncio.gather(*(chat.ask("a", ChatInput(message=q)) for q in scenario_questions("speed_bump")))
        deadline = time.monotonic() + 5
        while not chat.engine.clients["a"].waiting:
            assert time.monotonic() < deadline
            await asyncio.sleep(.02)
        snapshot = chat.snapshot()
        assert any(row["stage"] == "speed_bump" for row in snapshot["queue"])
        assert (await chat.ask("b", ChatInput(message="Hello"))).status_code == 200
        assert all(r.status_code == 200 for r in await responses)
        delayed = [row for row in chat.store.recent() if row["speed_bump"]["wait_ms"] > 0]
        assert delayed and max(row["speed_bump"]["wait_ms"] for row in delayed) >= 900
        assert chat.snapshot()["totals"]["waiting"] == 0
        assert chat.snapshot()["totals"]["delayed"] == len(delayed)
        assert chat.pending == 0
        await chat.close()
    asyncio.run(run())


def test_cancelling_a_delayed_request_releases_permits_and_records_error(tmp_path):
    async def run():
        chat = service(tmp_path)
        now = time.time()
        for q in scenario_questions("speed_bump")[:7]:
            chat.engine.observe("a", q, now)
        task = asyncio.create_task(chat.ask("a", ChatInput(message=scenario_questions("speed_bump")[-1])))
        while not chat.engine.clients["a"].waiting:
            await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not chat.runtime.calls
        assert chat.store.recent()[0]["status"] == "error"
        assert chat.pending == 0 and chat.slots._value == 2
        assert chat.engine.clients["a"].waiting == 0
        await chat.close()
    asyncio.run(run())


def test_approval_does_not_clear_a_block(tmp_path):
    async def run():
        chat = service(tmp_path)
        for q in scenario_questions("probing"):
            chat.engine.observe("a", q, time.time())
        approved = grant(chat)
        response = await chat.ask("a", ChatInput(message=QUESTIONS[0], bulk_pass_id=approved["id"]))
        assert response.status_code == 429
        assert json.loads(response.body)["action"] == "block"
        assert not chat.runtime.calls
        await chat.close()
    asyncio.run(run())


def test_production_disables_test_generation_but_allows_authenticated_grants(tmp_path):
    settings = Settings(data_dir=tmp_path, demo=False, keys={"private-client": "Customer"}, admin_token="operator-secret-" * 3)
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer " + settings.admin_token}
        alias = client.get("/api/chat/snapshot", headers=headers).json()["clients"][0]["id"]
        assert "private-client" not in alias
        assert client.post("/api/chat/tests/start", headers=headers, json={"client_id": alias, "scenario": "bulk"}).status_code == 403
        assert client.post("/api/chat/passes", headers=headers, json={"client_id": alias, "purpose": "Customer batch"}).status_code == 200
