"""Explicit protected-license operations; all operator secrets from ~/secrets.env."""

import argparse
import json
import sys
from pathlib import Path

import uvicorn
from dotenv import dotenv_values

from ara.licensing.server import (
    create_license_app,
    create_runtime,
    initialize_database,
    load_settings,
)

from .access_wire import hex_text, require
from .bundle import pack
from .server import ModelAccessService, Release, attach_model_access, initialize_model_access


def main(argv=None):
    runtime = None
    try:
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("init")
        serve = commands.add_parser("serve")
        serve.add_argument("--port", type=int, default=8766)
        package = commands.add_parser("pack")
        package.add_argument("--source", type=Path, required=True)
        package.add_argument("--output", type=Path, required=True)
        package.add_argument("--release-id", required=True)
        args = parser.parse_args(argv)
        values = dotenv_values(Path.home() / "secrets.env", interpolate=False)
        if args.command == "pack":
            raw_key = values.get("AIRA_MODEL_RELEASE_KEY")
            hex_text(raw_key)
            release_id, digest = pack(
                args.source, args.output, bytes.fromhex(raw_key), release_id=args.release_id
            )
            print(json.dumps({"release_id": release_id, "manifest_sha256": digest}))
            return 0
        runtime = create_runtime(load_settings(values=values))
        if args.command == "init":
            initialize_database(runtime.engine)
            initialize_model_access(runtime.engine)
        else:
            require(1024 <= args.port <= 65535)
            raw = values.get("AIRA_MODEL_RELEASES_JSON")
            require(type(raw) is str and 0 < len(raw) <= 16384)
            records = json.loads(raw)
            require(type(records) is list and 1 <= len(records) <= 16)
            releases = []
            for item in records:
                require(
                    type(item) is dict and set(item) == {"release_id", "manifest_sha256", "key"}
                )
                hex_text(item["key"])
                releases.append(
                    Release(item["release_id"], item["manifest_sha256"], bytes.fromhex(item["key"]))
                )
            app = create_license_app(runtime)
            attach_model_access(app, ModelAccessService(runtime, tuple(releases)))
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
        print("Protected model operation failed.", file=sys.stderr)
        return 1
    finally:
        if runtime is not None:
            runtime.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
