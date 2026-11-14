"""Describe a tested artifact, tied to its exact checkout; contains no credentials."""

import json
import os
import sys
from pathlib import Path

from common import build_for_run, digest, filename, version_for_run


def main():
    platform, installer, output = sys.argv[1:]
    installer = Path(installer)
    version = version_for_run(os.environ["GITHUB_RUN_NUMBER"])
    if installer.name != filename(platform, version):
        raise ValueError("installer filename mismatch")
    value = {
        "platform": platform,
        "version": version,
        "build": build_for_run(os.environ["GITHUB_RUN_NUMBER"]),
        "sha": os.environ["GITHUB_SHA"],
        "filename": installer.name,
        "bytes": installer.stat().st_size,
        "sha256": digest(installer),
    }
    Path(output).write_text(json.dumps(value, sort_keys=True) + "\n")
    print("Recorded tested artifact " + installer.name)


if __name__ == "__main__":
    main()
