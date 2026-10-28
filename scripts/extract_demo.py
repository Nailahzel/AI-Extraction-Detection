"""Label-only copying client for an explicitly owned loopback prediction API.

This module never imports the protected model, its corpus, or admin controls.
The evaluator owns the test set and measures agreement separately.
"""

import argparse
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline


def local_url(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "::1"}
        or parts.username
        or parts.password
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "Use your own loopback HTTP server, e.g. http://127.0.0.1:8766."
        )
    return url.rstrip("/")


def train_copy(pairs, seed=42):
    unique = {pair["text"]: pair["label"] for pair in pairs}
    if len(unique) < 8 or len(set(unique.values())) < 2:
        return None
    copied = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=20000),
        LogisticRegression(C=2, max_iter=1000, random_state=seed),
    )
    copied.fit(list(unique), list(unique.values()))
    return copied


def collect(
    url,
    key,
    candidates,
    *,
    attempts=120,
    seconds=8,
    interval=0.025,
    respect_retry=False,
):
    url = local_url(url)
    if (
        not candidates
        or attempts < 1
        or not math.isfinite(seconds)
        or seconds <= 0
        or not math.isfinite(interval)
        or interval < 0
    ):
        raise ValueError(
            "Supply inputs, a positive attempt/time budget and a nonnegative interval."
        )
    if any(
        not isinstance(text, str) or not text.strip() or len(text) > 2000
        for text in candidates
    ):
        raise ValueError(
            "Each candidate must be nonblank text of at most 2,000 characters."
        )
    pairs, records, index = [], [], 0
    first_denial = None
    before_denial = 0
    started = time.perf_counter()
    deadline = started + seconds
    with httpx.Client(base_url=url, trust_env=False, follow_redirects=False) as client:
        while (
            len(records) < attempts
            and index < len(candidates)
            and time.perf_counter() < deadline
        ):
            sent = time.perf_counter()
            response = client.post(
                "/predict",
                headers={"X-API-Key": key},
                json={"text": candidates[index]},
                timeout=max(0.001, min(10, deadline - sent)),
            )
            ended = time.perf_counter()
            if response.status_code not in {200, 429}:
                raise RuntimeError(
                    f"Prediction API returned HTTP {response.status_code}; experiment aborted."
                )
            body = response.json()
            record = {
                "input_index": index,
                "at_seconds": sent - started,
                "response_seconds": ended - started,
                "latency_ms": (ended - sent) * 1000,
                "status": response.status_code,
            }
            wait = interval
            if response.status_code == 200:
                if body.get("label") not in {"positive", "negative"}:
                    raise ValueError("Unexpected prediction schema.")
                # No confidence or hidden detector information enters training.
                pairs.append({"text": candidates[index], "label": body["label"]})
                if first_denial is None:
                    before_denial += 1
                index += 1
            else:
                if first_denial is None:
                    first_denial = ended - started
                retry = float(response.headers.get("Retry-After", "1"))
                if not math.isfinite(retry) or retry < 0:
                    raise ValueError("Invalid Retry-After value.")
                record["retry_after"] = retry
                if respect_retry:
                    wait = max(interval, retry)
                else:
                    index += 1
            records.append(record)
            if index < len(candidates) and len(records) < attempts:
                time.sleep(max(0, min(wait, deadline - time.perf_counter())))
    return {
        "attempted": len(records),
        "released": len(pairs),
        "withheld": len(records) - len(pairs),
        "released_before_first_denial": before_denial,
        "first_denial_seconds": first_denial,
        "elapsed_seconds": time.perf_counter() - started,
        "records": records,
        "pairs": pairs,
        "limits": {
            "attempts": attempts,
            "seconds": seconds,
            "interval": interval,
            "respect_retry_after": respect_retry,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--key", required=True)
    parser.add_argument(
        "--inputs",
        type=Path,
        required=True,
        help="JSON array of candidate strings; no test labels.",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("test-results/copied-model")
    )
    parser.add_argument("--attempts", type=int, default=120)
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--interval", type=float, default=0.025)
    parser.add_argument("--respect-retry-after", action="store_true")
    args = parser.parse_args()
    result = collect(
        args.url,
        args.key,
        json.loads(args.inputs.read_text(encoding="utf-8")),
        attempts=args.attempts,
        seconds=args.seconds,
        interval=args.interval,
        respect_retry=args.respect_retry_after,
    )
    copied = train_copy(result["pairs"])
    result["training_status"] = (
        "trained" if copied is not None else "insufficient training data"
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "collection.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    if copied is not None:
        joblib.dump(copied, args.output / "copy.joblib")
    else:
        (args.output / "copy.joblib").unlink(missing_ok=True)
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"records", "pairs"}
            },
            indent=2,
        )
    )
