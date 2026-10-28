"""Owned, authenticated loopback llama.cpp process. No cloud or tool execution."""

import asyncio
import os
import secrets
import socket
import subprocess

import httpx

from .config import ROOT

MODEL_NAME = "Qwen2.5-0.5B-Instruct · Q4_K_M"
MODEL_PATH = ROOT / "data/chat-model/qwen2.5-0.5b-instruct-q4_k_m.gguf"
RUNTIME_PATH = ROOT / ".tools/llama/llama-server.exe"


class ChatUnavailable(Exception):
    pass


class LocalChat:
    def __init__(self):
        self.process = None
        self.client = None
        self.log = None
        self.start_lock = asyncio.Lock()
        self.ready = False

    def status(self):
        installed = MODEL_PATH.is_file() and RUNTIME_PATH.is_file()
        return {
            "name": MODEL_NAME,
            "installed": installed,
            "ready": self.ready
            and self.process is not None
            and self.process.poll() is None,
            "setup": "python -m scripts.setup_chat",
        }

    async def start(self):
        async with self.start_lock:
            if self.status()["ready"]:
                return
            await self.close()
            if not self.status()["installed"]:
                raise ChatUnavailable(
                    "Install the local chat model: python -m scripts.setup_chat"
                )
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            token = secrets.token_urlsafe(40)
            env = os.environ.copy()
            env["LLAMA_API_KEY"] = token
            self.log = (MODEL_PATH.parent / "runtime.log").open("ab")
            try:
                self.process = subprocess.Popen(
                    [
                        str(RUNTIME_PATH),
                        "--model",
                        str(MODEL_PATH),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--ctx-size",
                        "8192",
                        "--parallel",
                        "2",
                        "--threads",
                        "4",
                        "--n-predict",
                        "160",
                        "--no-webui",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=self.log,
                    stderr=self.log,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self.client = httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=120,
                    trust_env=False,
                )
                for _ in range(240):
                    if self.process.poll() is not None:
                        break
                    try:
                        response = await self.client.get("/v1/models", timeout=1)
                        if response.status_code == 200:
                            self.ready = True
                            return
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.25)
            except OSError:
                pass
            await self.close()
            raise ChatUnavailable(
                "The local model could not start. Check data/chat-model/runtime.log."
            )

    async def reply(self, message, history):
        await self.start()
        messages = [
            {
                "role": "system",
                "content": "You are a helpful conversational assistant. Answer clearly and briefly. "
                "You cannot browse the internet or use tools. Admit when you do not know.",
            }
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": message})
        try:
            response = await self.client.post(
                "/v1/chat/completions",
                json={
                    "messages": messages,
                    "max_tokens": 160,
                    "temperature": 0.4,
                    "stream": False,
                },
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            answer = choice["message"]["content"].strip()
            if not answer:
                raise ValueError("Empty answer")
            return {
                "reply": answer,
                "truncated": choice.get("finish_reason") == "length",
            }
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise ChatUnavailable(
                "The local model could not answer. Try again shortly."
            ) from error

    async def close(self):
        self.ready = False
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    await asyncio.to_thread(self.process.wait, 5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    await asyncio.to_thread(self.process.wait, 5)
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
