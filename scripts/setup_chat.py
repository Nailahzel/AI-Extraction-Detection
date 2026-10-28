"""Download pinned official model/runtime artifacts and verify their SHA-256 hashes."""

import hashlib
import os
from pathlib import PurePosixPath
import shutil
import zipfile

import httpx

from modelshield.chat_runtime import MODEL_PATH, RUNTIME_PATH

RUNTIME_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b10894/llama-b10894-bin-win-cpu-x64.zip"
RUNTIME_SHA = "ab847167f848e1d49c9682dc6e742d1d27de23413689c7e0348d4f1477c5a389"
MODEL_URL = "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_SHA = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"


def checksum(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(client, url, path, expected):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and checksum(path) == expected:
        print(f"Verified {path.name}", flush=True)
        return
    partial = path.with_suffix(path.suffix + ".part")
    total = 0
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with partial.open("wb") as target:
            for chunk in response.iter_bytes(1024 * 1024):
                target.write(chunk)
                total += len(chunk)
                if total % (50 * 1024 * 1024) == 0:
                    print(f"{path.name}: {total // (1024 * 1024)} MiB", flush=True)
    if checksum(partial) != expected:
        raise RuntimeError(
            f"Checksum failed for {path.name}; artifact was not installed."
        )
    partial.replace(path)
    print(f"Verified {path.name}", flush=True)


def main():
    if os.name != "nt":
        raise SystemExit(
            "This bundled setup targets Windows x64. See README for runtime details."
        )
    archive = RUNTIME_PATH.parent.parent / "llama-b10894.zip"
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        download(client, RUNTIME_URL, archive, RUNTIME_SHA)
        destination = RUNTIME_PATH.parent.resolve()
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                path = PurePosixPath(member.filename.replace("\\", "/"))
                target = destination.joinpath(*path.parts).resolve()
                if path.is_absolute() or not target.is_relative_to(destination):
                    raise RuntimeError("Unsafe archive member")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as inp, target.open("wb") as out:
                        shutil.copyfileobj(inp, out)
        if not RUNTIME_PATH.is_file():
            raise RuntimeError(
                "Runtime archive did not contain llama-server.exe at the expected path."
            )
        download(client, MODEL_URL, MODEL_PATH, MODEL_SHA)
    print(
        "Local chat is installed. Run python enthi.py and open http://127.0.0.1:8765/chat",
        flush=True,
    )


if __name__ == "__main__":
    main()
