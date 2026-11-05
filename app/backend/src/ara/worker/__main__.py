"""Opt-in fixture worker CLI; never starts work when imported."""

import argparse
import json
import math
import os
import signal
import sys
from threading import Event

from ara.config import load_settings
from ara.db import create_database_engine

from . import WorkerSettings, run_once


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error includes arbitrary user-supplied values.
        self.exit(2, "Invalid worker arguments\n")


def main(argv=None):
    parser = _SafeParser(description="Local fixture worker (no semantic analysis)")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("--lease-seconds", type=float, default=30)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--run-timeout-seconds", type=float, default=900)
    parser.add_argument("--retry-delay-seconds", type=float, default=1)
    args = parser.parse_args(argv)
    engine = None
    handlers = {}
    try:
        if os.environ.get("ARA_ENVIRONMENT") != "local":
            raise ValueError("Local environment required")
        settings = WorkerSettings(
            lease_seconds=args.lease_seconds,
            max_attempts=args.max_attempts,
            run_timeout_seconds=args.run_timeout_seconds,
            retry_delay_seconds=args.retry_delay_seconds,
        )
        if not math.isfinite(args.poll_seconds) or not 0.01 <= args.poll_seconds <= 60:
            raise ValueError("Invalid polling interval")
        engine = create_database_engine(load_settings())
        stopped = Event()

        def stop(signum, frame):
            stopped.set()

        for signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, stop)
        while not stopped.is_set():
            outcome = run_once(engine, settings=settings)
            if args.once or outcome.outcome != "idle":
                print(
                    json.dumps(
                        {
                            "outcome": outcome.outcome,
                            "run_id": str(outcome.run_id) if outcome.run_id else None,
                        }
                    ),
                    flush=True,
                )
            if args.once:
                break
            stopped.wait(args.poll_seconds)
        return 0
    except Exception:
        print(
            "Local fixture worker failed; check configuration and storage availability",
            file=sys.stderr,
        )
        return 1
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
