"""Evaluator-owned helpers. Never imported by the copying client."""

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import socket
import threading
import time

import httpx
import numpy as np
import uvicorn

from modelshield.api import create_app
from modelshield.config import Settings


def fingerprint(value):
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def latency_summary(records):
    values = [row["latency_ms"] for row in records]
    return {
        "scope": "client round trip including HTTP and audit commit",
        "samples": len(values),
        "median_ms": float(np.median(values)) if values else None,
        "p95_ms": float(np.percentile(values, 95)) if values else None,
    }


@contextmanager
def local_server(data_dir):
    app = create_app(
        Settings(
            data_dir=Path(data_dir), admin_token="local-experiment-admin-credential"
        )
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    address = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("Isolated experiment server did not start.")
            time.sleep(0.05)
        yield address, {"Authorization": "Bearer local-experiment-admin-credential"}
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()
        if thread.is_alive():
            raise RuntimeError("Experiment server did not stop.")


def admin_post(client, path, body=None):
    response = client.post(path, json=body or {})
    response.raise_for_status()
    return response.json()
