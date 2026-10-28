"""Send repeatable traffic over real HTTP to a locally running ModelShield API."""

import argparse
import asyncio
from collections import Counter
import json
import time
from urllib.parse import urlparse

import httpx
from modelshield.traffic import PROFILES, session


async def run(args):
    if urlparse(args.url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "This demonstration traffic generator accepts loopback URLs only."
        )
    counts, started = Counter(), time.monotonic()
    async with httpx.AsyncClient(base_url=args.url, timeout=10) as client:
        for query in session(args.profile, args.seed, duration=args.duration):
            await asyncio.sleep(max(0, started + query.at - time.monotonic()))
            response = await client.post(
                "/predict", headers={"X-API-Key": query.key}, json={"text": query.text}
            )
            counts[response.status_code] += 1
    print(
        json.dumps(
            {"profile": args.profile, "seed": args.seed, "responses": dict(counts)},
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    if not 1 <= args.duration <= 300:
        parser.error("Duration must be 1-300 seconds.")
    asyncio.run(run(args))
