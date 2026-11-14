"""Explicit operator start; secrets come exclusively from ~/secrets.env."""

import argparse
import sys
from pathlib import Path

import uvicorn
from dotenv import dotenv_values

from ara.licensing.server import create_runtime
from ara.licensing.server import load_settings as license_settings

from .http import create_app
from .security import load_settings, need
from .service import Service, initialize


def main(argv=None):
    runtime = None
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("command", choices=["init", "serve"])
        parser.add_argument("--port", type=int, default=8767)
        args = parser.parse_args(argv)
        need(1024 <= args.port <= 65535)
        values = dotenv_values(Path.home() / "secrets.env", interpolate=False)
        runtime = create_runtime(license_settings(values=values))
        if args.command == "init":
            initialize(runtime.engine)
        else:
            app = create_app(Service(runtime, load_settings(values)))
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=args.port,
                proxy_headers=True,
                forwarded_allow_ips="127.0.0.1",
                access_log=False,
            )
        return 0
    except Exception:
        print("License admin operation failed.", file=sys.stderr)
        return 1
    finally:
        if runtime is not None:
            runtime.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
