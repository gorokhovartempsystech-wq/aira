"""Explicit build input download and deterministic model extraction."""

import argparse
import json
import os
import zipfile
from pathlib import Path

from common import build_for_run, download_pin, require_source, version_for_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=["windows-x64", "macos-arm64", "check"])
    parser.add_argument("work", type=Path)
    args = parser.parse_args()
    require_source(Path.cwd())
    number = os.environ["GITHUB_RUN_NUMBER"]
    version, build = version_for_run(number), build_for_run(number)
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "release.json").write_text(json.dumps({"version": version, "build": build}))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"version={version}\nbuild={build}\n")
    if args.platform == "check":
        return
    archive = download_pin("models", args.work)
    destination = args.work / "model"
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if sum(item.file_size for item in entries) > 2 * 1024**3:
            raise ValueError("model archive too large")
        for item in entries:
            if not (destination / item.filename).resolve().is_relative_to(destination.resolve()):
                raise ValueError("unsafe model archive entry")
        bundle.extractall(destination)
    models = destination / "models-protected"
    manifest = json.loads((models / "manifest.json").read_text())
    if manifest.get("protection", {}).get("format") != "aira-model/1" or list(
        models.rglob("*.onnx")
    ):
        raise ValueError("protected model required")
    download_pin(
        "windows-runtime" if args.platform == "windows-x64" else "macos-runtime", args.work
    )
    print("Verified pinned build inputs for " + args.platform)


if __name__ == "__main__":
    main()
