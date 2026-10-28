"""Protected chat API service and operator-only, bounded transcript audit."""

import asyncio
from collections import deque
from copy import deepcopy
import json
import sqlite3
import time
from typing import Literal
from uuid import uuid4

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .chat_engine import ChatRiskEngine, POLICY
from .chat_runtime import LocalChat, ChatUnavailable
from .bulk import BulkPasses


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=6)
    conversation_id: str = Field(
        default="manual", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    bulk_pass_id: str | None = Field(default=None, pattern=r"^BULK-[a-f0-9]{32}$")

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Please enter a message.")
        return value.strip()


class ChatAudit:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, at REAL NOT NULL, detail TEXT NOT NULL)"
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS chat_time ON requests(at)")
        self.db.execute(
            "DELETE FROM requests WHERE id NOT IN (SELECT id FROM requests ORDER BY at DESC LIMIT 5000)"
        )
        # A process restart cannot turn an incomplete request into an answered one.
        for record in self.recent(5000):
            if record["status"] == "pending":
                record.update(
                    status="error", error="Service restarted before completion."
                )
                self.write(record)
        self.db.commit()

    def write(self, record):
        self.db.execute(
            "INSERT INTO requests VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET detail=excluded.detail",
            (record["id"], record["at"], json.dumps(record)),
        )
        self.db.execute(
            "DELETE FROM requests WHERE id NOT IN (SELECT id FROM requests ORDER BY at DESC LIMIT 5000)"
        )
        self.db.commit()

    def recent(self, limit=100):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT detail FROM requests ORDER BY at DESC LIMIT ?", (limit,)
            ).fetchall()
        ]

    def close(self):
        self.db.close()


class ChatService:
    def __init__(self, settings, names):
        self.engine = ChatRiskEngine(names)
        self.runtime = LocalChat()
        self.store = ChatAudit(settings.data_dir / "chat.sqlite3")
        self.passes = BulkPasses(self.store.db)
        self.lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(2)
        self.client_slots = {key: asyncio.Semaphore(2) for key in names}
        self.pacing = {key: asyncio.Lock() for key in names}
        self.pass_slots = {}
        self.last_start = {}
        self.active = {}
        self.pending = 0
        self.alerts = deque(maxlen=100)
        self.started_at = time.time()

    def snapshot(self):
        now = time.time()
        clients = self.engine.view(now)
        return {
            "model": self.runtime.status(),
            "policy": POLICY,
            "clients": clients,
            "events": self.store.recent(),
            "alerts": list(self.alerts),
            "started_at": self.started_at,
            "now": now,
            "bulk_passes": self.passes.list(now),
            "queue": [deepcopy(record) for record in self.active.values()],
            "totals": {
                "requests": sum(c["total"] for c in clients),
                "answered": sum(c["answered"] for c in clients),
                "denied": sum(c["denied"] for c in clients),
                "errors": sum(c["errors"] for c in clients),
                "pending": self.pending,
                "waiting": sum(c["waiting"] for c in clients),
                "delayed": sum(c["delayed"] for c in clients),
                "delay_ms": round(sum(c["delay_ms"] for c in clients), 1),
            },
        }

    async def ask(self, key, payload):
        start = time.perf_counter()
        async with self.lock:
            now = time.time()
            bulk, bulk_error = (None, None)
            if payload.bulk_pass_id:
                bulk, bulk_error = self.passes.consume(payload.bulk_pass_id, key, now)
            action, retry = self.engine.observe(key, payload.message, now, approved=bulk is not None)
            state = self.engine.clients[key]
            record = {
                "id": uuid4().hex,
                "at": now,
                "client_id": key,
                "conversation_id": payload.conversation_id,
                "question": payload.message,
                "reply": None,
                "status": "pending",
                "action": action,
                "risk": state.risk,
                "signals": deepcopy(state.signals),
                "reasons": list(state.reasons),
                "policy": deepcopy(POLICY),
                "latency_ms": None,
                "incident_id": None,
                "bulk_pass_id": payload.bulk_pass_id,
                "bulk_pass": deepcopy(bulk),
                "raw_risk": state.raw_risk,
                "rate_credit": state.rate_credit,
                "stage": "queued",
                "speed_bump": {"seconds": self.engine.delay_seconds(key, now), "wait_ms": 0},
            }
            if action != "allow" and (
                now - state.last_alert >= 10
                or action == "block"
                and not any(
                    a["client_id"] == key
                    and a["action"] == "block"
                    and now - a["at"] < 30
                    for a in self.alerts
                )
            ):
                state.last_alert = now
                record["incident_id"] = "CHAT-" + uuid4().hex
                self.alerts.appendleft(deepcopy(record))
            if action != "allow":
                return self.denied(record, state, action, retry, start)
            if bulk_error:
                record["error"] = bulk_error
                return self.denied(record, state, "bulk_limit", 0, start)
            if self.pending >= 32:
                state.errors += 1
                record.update(status="error", error="The local model queue is full.")
                self.store.write(record)
                return JSONResponse({"detail": record["error"]}, status_code=503)
            self.pending += 1
            self.active[record["id"]] = record
            self.store.write(record)
            pass_slot = self.pass_slots.setdefault(bulk["id"], asyncio.Semaphore(bulk["concurrency"])) if bulk else asyncio.Semaphore(2)
        slot_acquired = False
        try:
            async with asyncio.timeout(180):
                async with self.client_slots[key], pass_slot:
                    denial = await self.wait_for_model(key, record, state, start)
                    if denial is not None:
                        return denial
                    slot_acquired = True
                    result = await self.runtime.reply(
                        payload.message, [item.model_dump() for item in payload.history]
                    )
                    async with self.lock:
                        action, retry = self.check_request(key, record, time.time())
                        if action != "allow":
                            return self.denied(record, state, action, retry, start)
                        state.answered += 1
                        record.update(
                            status="answered",
                            stage="complete",
                            reply=result["reply"],
                            truncated=result["truncated"],
                            latency_ms=round((time.perf_counter() - start) * 1000, 1),
                        )
                        self.store.write(record)
                        return JSONResponse(
                            {**result, "request_id": record["id"],
                             "processing": {"speed_bump_wait_ms": record["speed_bump"]["wait_ms"],
                                            "bulk_pass_used": bool(bulk)}},
                            headers={"Cache-Control": "no-store"},
                        )
        except (ChatUnavailable, TimeoutError) as error:
            async with self.lock:
                state.errors += 1
                message = str(error) or "The local model request timed out."
                record.update(
                    status="error",
                    stage="complete",
                    error=message,
                    latency_ms=round((time.perf_counter() - start) * 1000, 1),
                )
                self.store.write(record)
            return JSONResponse({"detail": message}, status_code=503)
        except asyncio.CancelledError:
            async with self.lock:
                state.errors += 1
                record.update(status="error", stage="complete", error="Request interrupted.")
                self.store.write(record)
            raise
        finally:
            if slot_acquired:
                self.slots.release()
            async with self.lock:
                self.pending -= 1
                self.active.pop(record["id"], None)
                # Semaphores for finished/expired grants need not live forever.
                active_passes = {row["bulk_pass_id"] for row in self.active.values()}
                for pass_id in list(self.pass_slots):
                    if pass_id not in active_passes:
                        self.pass_slots.pop(pass_id, None)

    def check_request(self, key, record, now):
        action, retry = self.engine.gate(key, now)
        if action != "allow":
            return action, retry
        if record["bulk_pass_id"]:
            error = self.passes.check(record["bulk_pass_id"], key, now, reserved=True)
            if error:
                record["error"] = error
                return "bulk_limit", 0
        return "allow", 0

    async def wait_for_model(self, key, record, state, start):
        """Space generation starts per key, before taking a scarce model slot.

        Recheck after every wait and again after slot acquisition. A burst cannot
        stack parallel timers to bypass spacing, or retain an answer after revoke.
        """
        acquired = False
        try:
            async with self.pacing[key]:
                while True:
                    async with self.lock:
                        now = time.time()
                        action, retry = self.check_request(key, record, now)
                        if action != "allow":
                            if acquired:
                                self.slots.release()
                                acquired = False
                            return self.denied(record, state, action, retry, start)
                        seconds = max(record["speed_bump"]["seconds"], self.engine.delay_seconds(key, now))
                        record["speed_bump"]["seconds"] = seconds
                        wait = max(0, max(record["at"], self.last_start.get(key, record["at"])) + seconds - now)
                        if acquired and wait <= 0:
                            self.last_start[key] = now
                            record["stage"] = "generating"
                            self.store.write(record)
                            return None  # Caller now owns and releases the model slot.
                        if acquired:
                            self.slots.release()
                            acquired = False
                        stage = "speed_bump" if wait > 0 else "model_queue"
                        if record["stage"] != stage:
                            record["stage"] = stage
                            self.store.write(record)
                    if wait > 0:
                        if not record["speed_bump"]["wait_ms"]:
                            state.delayed += 1
                        state.waiting += 1
                        began = time.perf_counter()
                        try:
                            await asyncio.sleep(min(wait, 0.25))
                        finally:
                            elapsed = (time.perf_counter() - began) * 1000
                            record["speed_bump"]["wait_ms"] = round(record["speed_bump"]["wait_ms"] + elapsed, 1)
                            state.delay_ms += elapsed
                            state.waiting -= 1
                    else:
                        await self.slots.acquire()
                        acquired = True
        except BaseException:
            if acquired:
                self.slots.release()
            raise

    def denied(self, record, state, action, retry, start):
        state.denied += 1
        record.update(
            status="withheld",
            stage="complete",
            action=action,
            latency_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        # If the restriction arose while this request was queued, retain both decisions.
        record["enforcement"] = {
            "risk": state.risk,
            "signals": deepcopy(state.signals),
            "reasons": list(state.reasons),
        }
        self.store.write(record)
        return JSONResponse(
            {
                "detail": record.get("error") if action == "bulk_limit" else "Request limit reached. Please pause before trying again.",
                "retry_after": retry,
                "action": action,
            },
            status_code=429,
            headers={**({"Retry-After": str(retry)} if retry else {}), "Cache-Control": "no-store"},
        )

    async def close(self):
        await self.runtime.close()
        self.store.close()
