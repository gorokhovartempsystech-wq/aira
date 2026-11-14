"""Build a fresh checkout using only pinned Python/PostgreSQL runtime components."""

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from common import filename


def run(*args):
    subprocess.run([str(value) for value in args], check=True)


def main():
    if platform.machine() != "arm64" or sys.platform != "darwin":
        raise SystemExit("An Apple Silicon macOS runner is required")
    work = Path(os.environ["RUNNER_TEMP"]) / "aira-release"
    run(sys.executable, "infra/desktop-release/prepare.py", "macos-arm64", work)
    release = json.loads((work / "release.json").read_text())
    mount = work / "runtime-volume"
    mount.mkdir()
    payload = work / "payload"
    payload.mkdir()
    run(
        "hdiutil",
        "attach",
        "-readonly",
        "-nobrowse",
        "-mountpoint",
        mount,
        work / "AIRA-0.2.7-apple-silicon.dmg",
    )
    try:
        old = mount / "AIRA.app/Contents/Resources/payload"
        for name in ("python", "pgsql"):
            shutil.copytree(
                old / name,
                payload / name,
                symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
    finally:
        run("hdiutil", "detach", mount)
    runtime = payload / "python/bin/python3.12"
    run(runtime, "--version")
    run(payload / "pgsql/bin/postgres", "--version")
    requirements = work / "requirements-runtime.txt"
    requirements.write_text(
        "\n".join(
            line
            for line in Path("app/backend/requirements.lock").read_text().splitlines()
            if not line.startswith(("pytest", "ruff", "iniconfig", "pluggy", "Pygments"))
        )
    )
    run(
        runtime,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--upgrade",
        "-r",
        requirements,
        "-r",
        "engine/requirements-engine.txt",
    )
    for name in ("src", "migrations"):
        shutil.copytree(
            Path("app/backend") / name,
            payload / "app/backend" / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copy2("app/backend/alembic.ini", payload / "app/backend/alembic.ini")
    shutil.copytree("app/frontend/static", payload / "app/frontend/static")
    shutil.copy2("app/frontend/aira_host.py", payload / "app/frontend/aira_host.py")
    run(
        runtime,
        "tools/prepare_ml_bundle.py",
        "--models",
        work / "model/models-protected",
        "--destination",
        payload / "app/backend/ml_bundle",
    )
    run(sys.executable, "infra/desktop-release/backend_gate.py", payload / "pgsql/bin")
    if list(payload.rglob("secrets.env")) or list(
        (payload / "app/backend/ml_bundle/models").rglob("*.onnx")
    ):
        raise ValueError("operator settings or plaintext models must not enter the installer")
    run(sys.executable, "app/frontend/packaging/updates/fetch_sdk.py", "macos", work / "sparkle")
    output = work / "release"
    output.mkdir()
    installer = output / filename("macos-arm64", release["version"])
    run(
        sys.executable,
        "app/frontend/packaging/macos/build.py",
        "--payload",
        payload,
        "--sparkle",
        work / "sparkle",
        "--version",
        release["version"],
        "--build",
        release["build"],
        "--output",
        installer,
    )
    run("hdiutil", "verify", installer)
    run(
        sys.executable,
        "infra/desktop-release/smoke_macos.py",
        installer,
        release["version"],
        release["build"],
    )
    run(
        sys.executable,
        "infra/desktop-release/receipt.py",
        "macos-arm64",
        installer,
        output / "macos-arm64.json",
    )


if __name__ == "__main__":
    main()
