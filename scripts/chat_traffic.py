"""Send ordinary conversation or an extraction-like burst to an owned local chat API."""

import argparse
import asyncio
import json
from urllib.parse import urlsplit

import httpx

QUESTIONS = [
    "Why is the sky blue?",
    "How do plants grow?",
    "What is a neural network?",
    "Write a friendly greeting.",
    "Explain gravity in a sentence.",
    "What is an API?",
]


async def run(args):
    async with httpx.AsyncClient(
        base_url=args.url, timeout=190, trust_env=False
    ) as client:

        async def send(index):
            question = (
                QUESTIONS[index % len(QUESTIONS)]
                if args.profile == "normal"
                else (
                    f"Explain how a neural network learns from examples. Keep answer {index + 1} to one sentence."
                )
            )
            response = await client.post(
                "/chat/messages",
                headers={"X-API-Key": args.key},
                json={"message": question, "conversation_id": "traffic-demo"},
            )
            print(
                json.dumps(
                    {
                        "request": index + 1,
                        "status": response.status_code,
                        "result": response.json(),
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )

        if args.profile == "normal":
            for index in range(args.count):
                await send(index)
                if index + 1 < args.count:
                    await asyncio.sleep(5)
        else:
            await asyncio.gather(*(send(index) for index in range(args.count)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--profile", choices=["normal", "extraction"], required=True)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--key")
    args = parser.parse_args()
    target = urlsplit(args.url)
    if (
        target.scheme != "http"
        or target.hostname not in {"127.0.0.1", "::1"}
        or target.username
        or target.password
        or target.path not in {"", "/"}
        or target.query
        or target.fragment
    ):
        parser.error(
            "Use an owned literal loopback HTTP address, such as http://127.0.0.1:8765"
        )
    if not 1 <= args.count <= 30:
        parser.error("Count must be between 1 and 30")
    args.key = args.key or ("normal-01" if args.profile == "normal" else "probe-01")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
