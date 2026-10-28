"""Launch ModelShield: python enthi.py. All inference runs locally."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        description="ModelShield - AI model extraction defense"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        import uvicorn
        from modelshield.api import create_app
        from modelshield.config import Settings
    except ModuleNotFoundError:
        print("Install dependencies first: python -m pip install -r requirements.txt")
        return 1
    settings = Settings()
    if settings.demo and args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error(
            "Demo mode is loopback-only. See README for explicit non-demo configuration."
        )
    print(
        f"\n  ModelShield / AI model extraction defense\n  Chatbot:   http://{args.host}:{args.port}/chat\n  Dashboard: http://{args.host}:{args.port}/dashboard\n  API docs:  http://{args.host}:{args.port}/docs\n  Mode: {'local demonstration' if settings.demo else 'authenticated service'}\n"
    )
    uvicorn.run(
        create_app(settings),
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
