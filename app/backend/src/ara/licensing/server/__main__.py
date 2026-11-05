"""Explicit local operator commands. Keys never come from argv or appear in output."""

import argparse
import sys

import uvicorn

from ara.licensing import LicenseError
from ara.licensing._models import uuid_text

from . import (
    ServerError,
    create_license_app,
    create_runtime,
    initialize_database,
    issue_license,
    load_settings,
    set_enabled,
)
from ._models import fail, require


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        fail("validation_error")


def _arguments(argv):
    parser = _Parser(prog="aira-license-server")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8766)
    for operation in ("issue", "disable", "enable"):
        command = commands.add_parser(operation)
        command.add_argument("--license-id", type=uuid_text, required=True)
        if operation == "issue":
            command.add_argument("--duration-seconds", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "serve":
        require(1024 <= args.port <= 65535)
    return args


def main(argv=None):
    runtime = None
    try:
        args = _arguments(argv)
        settings = load_settings(for_issue=args.command == "issue")
        runtime = create_runtime(settings)
        if args.command == "init":
            initialize_database(runtime.engine)
        elif args.command == "serve":
            uvicorn.run(
                create_license_app(runtime),
                host="127.0.0.1",
                port=args.port,
                proxy_headers=True,
                forwarded_allow_ips="127.0.0.1",
                access_log=False,
            )
        elif args.command == "issue":
            issue_license(
                runtime,
                license_id=args.license_id,
                key=settings.issue_key,
                duration_seconds=args.duration_seconds,
            )
        else:
            set_enabled(runtime, license_id=args.license_id, enabled=args.command == "enable")
        print("License operation completed.")
        return 0
    except (ServerError, LicenseError) as error:
        print("License operation failed: " + error.code, file=sys.stderr)
        return 2
    except Exception:
        print("License operation failed.", file=sys.stderr)
        return 1
    finally:
        if runtime is not None:
            try:
                runtime.engine.dispose()
            except Exception:
                print("License storage cleanup failed.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
