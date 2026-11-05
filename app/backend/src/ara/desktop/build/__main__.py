"""Opt-in build command; no discovery of runtime credentials or executable launch."""

import argparse
import json
import os
import sys
from pathlib import Path

from ara.desktop.installation._files import _admit, _stamp
from ara.desktop.installation._manifest import _json

from . import BuildError, build_payload
from ._models import require


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BuildError("validation_error") from None


def _roles(path):
    try:
        initial = path.lstat()
        _admit(initial)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            _admit(opened)
            require(_stamp(opened) == _stamp(initial) and 0 < opened.st_size <= 65536)
            blocks, count = [], 0
            while count <= 65536:
                data = os.read(fd, 65537 - count)
                if not data:
                    break
                count += len(data)
                blocks.append(data)
            require(count == opened.st_size and _stamp(os.fstat(fd)) == _stamp(opened))
            return _json(b"".join(blocks))
        finally:
            os.close(fd)
    except Exception:
        raise BuildError("validation_error") from None


def main(argv=None):
    try:
        parser = _Parser(
            description="Build a verified private payload from explicitly staged files"
        )
        for name in ("source", "destination", "version", "target", "kind", "roles"):
            parser.add_argument("--" + name, required=True)
        parser.add_argument("--extra-executable", action="append", default=[])
        args = parser.parse_args(argv)
        receipt = build_payload(
            Path(args.source),
            Path(args.destination),
            version=args.version,
            target=args.target,
            kind=args.kind,
            entrypoints=_roles(Path(args.roles)),
            extra_executables=tuple(args.extra_executable),
        )
        manifest = receipt.installation.manifest
        print(
            json.dumps(
                dict(
                    manifest_sha256=receipt.manifest_sha256,
                    version=manifest.version,
                    target=manifest.target,
                    kind=manifest.kind,
                    files=len(manifest.files),
                    bytes=manifest.total_bytes,
                ),
                sort_keys=True,
            )
        )
        return 0
    except Exception as error:
        code = error.code if isinstance(error, BuildError) else "build_failed"
        print(json.dumps({"code": code}, sort_keys=True), file=sys.stderr)
        return 2 if code == "validation_error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
