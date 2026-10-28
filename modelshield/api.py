"""FastAPI application and loopback-only demonstration control plane."""

import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import json
import secrets
import time
from copy import deepcopy
from uuid import uuid4
from typing import Literal

import httpx
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, Settings
from .requirements import build_evidence, load_report, REPORT_FILES
from .chat import ChatInput, ChatService
from .chat_engine import POLICY as CHAT_POLICY
from .bulk import BulkPassInput
from .chat_scenarios import scenario_questions
from .engine import RiskEngine
from .model import SentimentModel
from .storage import AuditStore
from .traffic import demo_queries


class BodyLimitMiddleware:
    def __init__(self, app, limit=16384):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse(
                    {"detail": "Request body exceeds 16 KiB."}, status_code=413
                )(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()

        return await self.app(scope, replay, send)


class PredictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Text must contain a non-whitespace character.")
        return value


class DemoInput(BaseModel):
    scenario: str = "guided"
    seed: int = Field(default=42, ge=0, le=1000000)


class ModeInput(BaseModel):
    enforce: bool


class ChatDemoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_id: str = Field(min_length=1, max_length=128)
    scenario: Literal["speed_bump", "probing", "bulk"]


class Service:
    def __init__(self, settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.admin_token = settings.admin_token or secrets.token_urlsafe(40)
        self.model = SentimentModel()
        self.key_lookup = {
            hashlib.sha256(key.encode()).hexdigest(): (
                key
                if settings.demo
                else "key-" + hashlib.sha256(key.encode()).hexdigest()[:8]
            )
            for key in settings.keys
        }
        self.client_names = {
            self.key_lookup[hashlib.sha256(key.encode()).hexdigest()]: name
            for key, name in settings.keys.items()
        }
        self.engine = RiskEngine(self.model, self.client_names)
        self.chat = ChatService(settings, self.client_names)
        self.store = AuditStore(settings.data_dir / "audit.sqlite3")
        self.lock = asyncio.Lock()
        self.enforcing = True
        self.started_at = time.time()
        self.alerts = deque(maxlen=100)
        self.timeline = deque(maxlen=5000)
        self.latencies = deque(maxlen=500)
        self.demo_task = None
        self.chat_demo_task = None
        self.chat_demo = {"running": False, "completed": 0, "total": 0, "responses": {}}
        self.demo = {
            "running": False,
            "scenario": None,
            "sent": 0,
            "errors": 0,
            "started_at": None,
        }

    def identify(self, secret):
        if not secret:
            raise HTTPException(401, "A valid X-API-Key header is required.")
        client_id = self.key_lookup.get(hashlib.sha256(secret.encode()).hexdigest())
        if not client_id:
            raise HTTPException(401, "A valid X-API-Key header is required.")
        return client_id

    def alert(self, client_id, now, action):
        state = self.engine.clients[client_id]
        if (
            state.risk < self.engine.policy["throttle_threshold"]
            or now - state.last_alert < 10
        ):
            return None
        state.last_alert = now
        incident_id = "ALT-" + uuid4().hex
        self.alerts.appendleft(
            {
                "id": incident_id,
                "at": now,
                "client_id": client_id,
                "risk": state.risk,
                "action": action,
                "reasons": list(state.reasons),
                "signals": deepcopy(state.signals),
                "campaign": state.campaign,
                "policy": deepcopy(self.engine.policy),
                "campaign_evidence": deepcopy(
                    next(
                        (c for c in self.engine.campaigns if c["id"] == state.campaign),
                        None,
                    )
                ),
            }
        )
        return incident_id

    async def predict(self, client_id, text):
        started = time.perf_counter()
        async with self.lock:
            now = time.time()
            state = self.engine.clients[client_id]
            state.total += 1
            state.last_seen = now
            action, retry = (
                self.engine.gate(client_id, now) if self.enforcing else ("allow", 0)
            )
            label, confidence = None, None
            if action == "allow":
                label, confidence = self.model.predict(text)
                self.engine.observe(client_id, text, confidence, now)
                if self.enforcing:
                    action, retry = self.engine.enforce(client_id, now)
            denied = action != "allow"
            state.denied += int(denied)
            state.answered += int(not denied)
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            self.latencies.append(elapsed)
            self.timeline.append((now, denied))
            incident_id = self.alert(
                client_id, now, action if self.enforcing else "observed"
            )
            detail = {
                "label": label if not denied else None,
                "confidence": confidence if not denied else None,
                "reasons": list(state.reasons),
                "signals": dict(state.signals),
                "campaign": state.campaign,
                "incident_id": incident_id,
                "campaign_evidence": deepcopy(
                    next(
                        (c for c in self.engine.campaigns if c["id"] == state.campaign),
                        None,
                    )
                ),
                "policy": deepcopy(self.engine.policy),
                "enforcing": self.enforcing,
                "latency_scope": "server processing before audit commit and response serialization",
            }
            self.store.record(now, client_id, action, state.risk, elapsed, detail)
            if denied:
                # Do not expose model answers or detector details to the denied caller.
                return JSONResponse(
                    {
                        "detail": "Behavioral request limit reached.",
                        "action": action,
                        "retry_after": retry,
                    },
                    status_code=429,
                    headers={"Retry-After": str(retry), "Cache-Control": "no-store"},
                )
            return JSONResponse(
                {"label": label, "confidence": confidence},
                headers={"Cache-Control": "no-store"},
            )

    async def stop_demo(self):
        if self.demo_task and not self.demo_task.done():
            self.demo_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.demo_task
        self.demo["running"] = False

    async def stop_chat_demo(self):
        if self.chat_demo_task and not self.chat_demo_task.done():
            self.chat_demo_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.chat_demo_task
            self.chat_demo["cancelled"] = True
        self.chat_demo["running"] = False

    async def run_chat_demo(self, app, key, questions, pass_id):
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
                async def send(question):
                    response = await client.post("/chat/messages", headers={"X-API-Key": key}, json={
                        "message": question, "conversation_id": self.chat_demo["id"], "bulk_pass_id": pass_id,
                    })
                    code = str(response.status_code)
                    self.chat_demo["responses"][code] = self.chat_demo["responses"].get(code, 0) + 1
                    self.chat_demo["completed"] += 1
                # Structured cancellation waits for every pending request to be audited.
                async with asyncio.TaskGroup() as group:
                    for question in questions:
                        group.create_task(send(question))
        except asyncio.CancelledError:
            raise
        except Exception:
            self.chat_demo["error"] = "Demo could not complete; inspect request errors below."
        finally:
            self.chat_demo.update(running=False, finished_at=time.time())

    async def run_demo(self, app, scenario, seed):
        self.demo = {
            "running": True,
            "scenario": scenario,
            "sent": 0,
            "errors": 0,
            "started_at": time.time(),
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as client:
                for query in demo_queries(scenario, seed):
                    await asyncio.sleep(max(0, start + query.at - time.monotonic()))
                    response = await client.post(
                        "/predict",
                        headers={"X-API-Key": query.key},
                        json={"text": query.text},
                    )
                    self.demo["sent"] += 1
                    if response.status_code not in {200, 429}:
                        self.demo["errors"] += 1
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.demo["errors"] += 1
            self.demo["error"] = type(error).__name__
        finally:
            self.demo["running"] = False

    def snapshot(self):
        now = time.time()
        clients = self.engine.refresh(now)
        points = [
            {"at": int(now) - 59 + i, "allowed": 0, "denied": 0} for i in range(60)
        ]
        for at, denied in self.timeline:
            offset = int(at) - points[0]["at"]
            if 0 <= offset < 60:
                points[offset]["denied" if denied else "allowed"] += 1
        active = [client for client in clients if client["total"]]
        return {
            "now": now,
            "started_at": self.started_at,
            "demo_mode": self.settings.demo,
            "enforcing": self.enforcing,
            "totals": {
                "requests": sum(c["total"] for c in clients),
                "denied": sum(c["denied"] for c in clients),
                "answered": sum(c["answered"] for c in clients),
                "active_keys": len(active),
                "at_risk": sum(
                    bool(c["risk"] >= self.engine.policy["throttle_threshold"])
                    for c in active
                ),
                "latency_p95": (
                    round(float(np.percentile(self.latencies, 95)), 2)
                    if self.latencies
                    else 0
                ),
            },
            "clients": clients,
            "alerts": list(self.alerts),
            "campaigns": self.engine.campaigns,
            "timeline": points,
            "events": self.store.recent(40),
            "demo": self.demo,
            "model": self.model.metadata(),
            "policy": self.engine.policy,
        }


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = Service(settings)
        yield
        await app.state.service.stop_demo()
        await app.state.service.stop_chat_demo()
        await app.state.service.chat.close()
        app.state.service.store.close()

    app = FastAPI(
        title="ModelShield",
        description="Explainable behavioral defense against model extraction.",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Never echo invalid inputs (including NaN/Infinity) into JSON responses.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]
            },
        )

    app.add_middleware(BodyLimitMiddleware)
    if settings.demo:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
        )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path not in {"/docs", "/redoc"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        if request.url.path.startswith("/api/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    def service(request: Request):
        return request.app.state.service

    def admin(request: Request, svc=Depends(service)):
        authorization = request.headers.get("authorization", "")
        token = (
            authorization[7:]
            if authorization.startswith("Bearer ")
            else request.cookies.get("modelshield_admin", "")
        )
        if not token or not hmac.compare_digest(
            token.encode("utf-8"), svc.admin_token.encode("utf-8")
        ):
            raise HTTPException(401, "Administrator authentication required.")
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                raise HTTPException(
                    403, "Cross-origin administrative requests are not permitted."
                )
        return svc

    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    @app.get("/classifier-lab", include_in_schema=False)
    async def index(request: Request, svc=Depends(service)):
        page = "index.html" if request.url.path == "/classifier-lab" else "monitor.html"
        response = FileResponse(
            ROOT / "web" / page, headers={"Cache-Control": "no-store"}
        )
        if (
            settings.demo
            and request.client
            and request.client.host in {"127.0.0.1", "::1"}
        ):
            response.set_cookie(
                "modelshield_admin",
                svc.admin_token,
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
                max_age=28800,
            )
        return response

    @app.get("/chat", include_in_schema=False)
    async def chat_page():
        return FileResponse(
            ROOT / "web" / "chat.html", headers={"Cache-Control": "no-store"}
        )

    @app.get("/chat/status")
    async def chat_status(svc=Depends(service)):
        return {"model": svc.chat.runtime.status(), "demo": settings.demo}

    @app.get("/chat/examples")
    async def chat_examples():
        return {"questions": scenario_questions("bulk")}

    @app.post("/chat/messages")
    async def chat_message(
        payload: ChatInput,
        x_api_key: str | None = Header(default=None),
        svc=Depends(service),
    ):
        return await svc.chat.ask(svc.identify(x_api_key), payload)

    @app.get("/api/chat/snapshot")
    async def chat_snapshot(svc=Depends(admin)):
        async with svc.chat.lock:
            return {**svc.chat.snapshot(), "demo_mode": settings.demo, "test_run": deepcopy(svc.chat_demo)}

    @app.get("/chat/access")
    async def chat_access(x_api_key: str | None = Header(default=None), svc=Depends(service)):
        key = svc.identify(x_api_key)
        async with svc.chat.lock:
            grant = svc.chat.passes.current(key, time.time())
            return JSONResponse({"bulk_pass": grant}, headers={"Cache-Control": "no-store"})

    @app.post("/api/chat/passes")
    async def issue_chat_pass(payload: BulkPassInput, svc=Depends(admin)):
        if payload.client_id not in svc.client_names:
            raise HTTPException(404, "Unknown client.")
        async with svc.chat.lock:
            return svc.chat.passes.issue(payload, time.time())

    @app.post("/api/chat/passes/{pass_id}/revoke")
    async def revoke_chat_pass(pass_id: str, svc=Depends(admin)):
        async with svc.chat.lock:
            return svc.chat.passes.revoke(pass_id, time.time())

    @app.post("/api/chat/tests/start")
    async def start_chat_test(payload: ChatDemoInput, svc=Depends(admin)):
        if not settings.demo:
            raise HTTPException(403, "Traffic generation is disabled outside demo mode.")
        if payload.client_id not in svc.client_names:
            raise HTTPException(404, "Unknown client.")
        async with svc.chat.lock:
            if svc.chat_demo_task and not svc.chat_demo_task.done():
                raise HTTPException(409, "A chat test is already running. Stop it or wait for completion.")
            now = time.time()
            state = svc.chat.engine.clients[payload.client_id]
            if state.last_seen and now - state.last_seen < CHAT_POLICY["window_seconds"]:
                raise HTTPException(409, "Choose an unused client or wait 60 seconds after its last request for a repeatable test. No traffic was cleared.")
            grant = svc.chat.passes.current(payload.client_id, now)
            pass_id = grant["id"] if grant and grant["status"] == "active" else None
            if payload.scenario == "bulk" and (not grant or grant["remaining"] < 30):
                raise HTTPException(409, "Approve a fresh 30-request bulk pass for this client first.")
            questions = scenario_questions(payload.scenario)
            key = next(secret for secret in settings.keys if svc.identify(secret) == payload.client_id)
            svc.chat_demo = {"id": "demo-" + uuid4().hex, "running": True, "scenario": payload.scenario,
                             "client_id": payload.client_id, "total": len(questions), "completed": 0,
                             "responses": {}, "started_at": now, "bulk_pass_id": pass_id}
            svc.chat_demo_task = asyncio.create_task(svc.run_chat_demo(app, key, questions, pass_id))
            return deepcopy(svc.chat_demo)

    @app.post("/api/chat/tests/stop")
    async def stop_chat_test(svc=Depends(admin)):
        await svc.stop_chat_demo()
        return deepcopy(svc.chat_demo)

    @app.get("/api/chat/export")
    async def chat_export(svc=Depends(admin)):
        async with svc.chat.lock:
            content = json.dumps(
                {
                    "exported_at": time.time(),
                    "policy": CHAT_POLICY,
                    "events": svc.chat.store.recent(5000),
                    "bulk_passes": svc.chat.passes.list(time.time()),
                },
                indent=2,
            )
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="modelshield-chat-evidence.json"'
            },
        )

    @app.get("/api/requirements")
    async def requirements_evidence(download: bool = False, svc=Depends(admin)):
        content = json.dumps(build_evidence(svc), allow_nan=False)
        headers = (
            {
                "Content-Disposition": 'attachment; filename="modelshield-requirements-evidence.json"'
            }
            if download
            else {}
        )
        return Response(content, media_type="application/json", headers=headers)

    @app.get("/api/requirements/reports/{name}")
    async def requirements_report(name: str, svc=Depends(admin)):
        if name not in REPORT_FILES:
            raise HTTPException(404, "Unknown evidence report.")
        report = load_report(name)
        if not report["available"]:
            raise HTTPException(404, report["message"])
        return Response(
            json.dumps(report["data"], allow_nan=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{REPORT_FILES[name]}"'
            },
        )

    @app.get("/health")
    async def health(svc=Depends(service)):
        return {"status": "ok", "model": svc.model.name, "version": "1.0.0"}

    @app.post("/predict")
    async def predict(
        payload: PredictInput,
        x_api_key: str | None = Header(default=None),
        svc=Depends(service),
    ):
        return await svc.predict(svc.identify(x_api_key), payload.text)

    @app.get("/api/snapshot")
    async def snapshot(svc=Depends(admin)):
        async with svc.lock:
            return svc.snapshot()

    @app.post("/api/demo/start")
    async def start_demo(payload: DemoInput, svc=Depends(admin)):
        if not settings.demo:
            raise HTTPException(
                403, "Traffic generation is disabled outside demo mode."
            )
        try:
            demo_queries(payload.scenario, payload.seed)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if svc.demo_task and not svc.demo_task.done():
            raise HTTPException(409, "A simulation is already running.")
        svc.demo_task = asyncio.create_task(
            svc.run_demo(app, payload.scenario, payload.seed)
        )
        return {"started": True, "scenario": payload.scenario}

    @app.post("/api/demo/stop")
    async def stop_demo(svc=Depends(admin)):
        await svc.stop_demo()
        return {"stopped": True}

    @app.post("/api/reset")
    async def reset(svc=Depends(admin)):
        if not settings.demo:
            raise HTTPException(403, "Reset is disabled outside demo mode.")
        await svc.stop_demo()
        async with svc.lock:
            svc.engine = RiskEngine(svc.model, svc.client_names)
            svc.store.clear()
            svc.alerts.clear()
            svc.timeline.clear()
            svc.latencies.clear()
            svc.started_at = time.time()
            svc.demo = {
                "running": False,
                "scenario": None,
                "sent": 0,
                "errors": 0,
                "started_at": None,
            }
        return {"reset": True}

    @app.post("/api/mode")
    async def mode(payload: ModeInput, svc=Depends(admin)):
        async with svc.lock:
            svc.enforcing = payload.enforce
            if not payload.enforce:
                for state in svc.engine.clients.values():
                    state.blocked_until = state.throttled_until = 0
        return {"enforcing": svc.enforcing}

    @app.get("/api/export")
    async def export(svc=Depends(admin)):
        async with svc.lock:
            content = json.dumps(
                {
                    "exported_at": time.time(),
                    "policy": svc.engine.policy,
                    "events": svc.store.export(),
                },
                indent=2,
            )
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="modelshield-evidence.json"'
            },
        )

    @app.get("/api/evaluation")
    async def evaluation(svc=Depends(admin)):
        path = ROOT / "reports" / "evaluation.json"
        if not path.exists():
            return {
                "available": False,
                "message": "Run python -m scripts.evaluate to generate measured results.",
            }
        return {"available": True, **json.loads(path.read_text(encoding="utf-8"))}

    @app.get("/api/incidents/{incident_id}")
    async def incident(incident_id: str, svc=Depends(admin)):
        async with svc.lock:
            record = svc.store.incident(incident_id)
        if record is None:
            raise HTTPException(
                404, "Incident is unavailable or outside audit retention."
            )
        return record

    @app.get("/api/experiments")
    async def experiments(svc=Depends(admin)):
        result = {}
        for name in ("copy-experiment", "defense-comparison"):
            path = ROOT / "reports" / f"{name}.json"
            result[name] = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            )
        return result

    @app.get("/api/submission")
    async def submission(svc=Depends(admin)):
        path = ROOT / "reports" / "ModelShield-submission.pdf"
        if not path.exists():
            raise HTTPException(
                404, "Run python -m scripts.submission to generate the submission."
            )
        return FileResponse(path, filename=path.name, media_type="application/pdf")

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    return app
