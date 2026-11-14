"""Run the existing backend gate against a new socket-only PostgreSQL 18 cluster."""

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def main():
    binaries = Path(sys.argv[1]).resolve()
    root = Path("app/backend").resolve()
    runtime = root / ".runtime"
    runtime.mkdir(mode=0o700)
    cluster = runtime / "postgres18"
    cluster.mkdir(mode=0o700)
    identity = {"project": str(root), "uid": os.getuid(), "major": 18}
    (cluster / "owner.json").write_text(json.dumps(identity))
    (cluster / "owner.json").chmod(0o600)
    socket = Path(
        "/private/tmp/ara-pg-"
        + str(os.getuid())
        + "-"
        + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    )
    socket.mkdir(mode=0o700)
    (socket / "owner.json").write_text(json.dumps(identity))
    (socket / "owner.json").chmod(0o600)
    data = cluster / "data"
    subprocess.run(
        [
            str(binaries / "initdb"),
            "-D",
            str(data),
            "--encoding=UTF8",
            "--locale=C",
            "--auth-local=peer",
            "--auth-host=scram-sha-256",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    options = shlex.join(
        [
            "-h",
            "",
            "-k",
            str(socket),
            "-p",
            "5432",
            "-c",
            "unix_socket_permissions=0700",
            "-c",
            "max_connections=40",
            "-c",
            "shared_buffers=32MB",
        ]
    )
    subprocess.run(
        [
            str(binaries / "pg_ctl"),
            "-D",
            str(data),
            "-l",
            str(cluster / "postgres.log"),
            "-o",
            options,
            "-w",
            "start",
        ],
        check=True,
    )
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(root / ".venv")],
            check=True,
        )
        subprocess.run(["bash", "scripts/check.sh"], cwd=root, check=True)
    finally:
        subprocess.run(
            [str(binaries / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=True
        )
        (socket / "owner.json").unlink()
        socket.rmdir()


if __name__ == "__main__":
    main()
