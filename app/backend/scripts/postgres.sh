#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec "$project_dir/.venv/bin/python" - "$project_dir" "${1:-status}" <<'PY'
"""Manage only this project's PostgreSQL cluster; never load secrets."""
import fcntl
import hashlib
import json
import os
import pwd
import shlex
import stat
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
action = sys.argv[2]
if action not in {"start", "stop", "status", "check"}:
    raise SystemExit("Usage: bash scripts/postgres.sh {start|stop|status|check}")

uid = os.getuid()
username = pwd.getpwuid(uid).pw_name
fingerprint = hashlib.sha256(str(root).encode()).hexdigest()[:16]
runtime = root / ".runtime"
bundle = runtime / "Postgres.app"
bin_dir = bundle / "Contents/Versions/18/bin"
cluster = runtime / "postgres18"
data = cluster / "data"
socket_dir = Path(f"/private/tmp/ara-pg-{uid}-{fingerprint}")
port = "5432"  # Unique socket directory; TCP listening is disabled.
identity = {"project": str(root), "uid": uid, "major": 18}
child_env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C", "LC_ALL": "C"}


def fail(message):
    raise SystemExit(message)


def owned_dir(path, create=False, marked=False):
    if not path.exists() and not path.is_symlink():
        if not create:
            fail(f"Missing directory: {path}")
        path.mkdir(mode=0o700)
        if marked:
            marker = path / "owner.json"
            with marker.open("x") as handle:
                json.dump(identity, handle)
            marker.chmod(0o600)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
        fail(f"Refusing foreign or symlink directory: {path}")
    if marked:
        if stat.S_IMODE(info.st_mode) != 0o700:
            fail(f"Directory must have mode 0700: {path}")
        marker = path / "owner.json"
        if marker.is_symlink() or not marker.is_file() or marker.stat().st_uid != uid:
            fail(f"Missing or unsafe ownership marker: {path}")
        try:
            actual = json.loads(marker.read_text())
        except (ValueError, OSError):
            fail(f"Invalid ownership marker: {path}")
        if actual != identity:
            fail(f"Ownership marker belongs to another project: {path}")


def run(arguments, check=True):
    result = subprocess.run(
        [str(item) for item in arguments], env=child_env, text=True, capture_output=True
    )
    if check and result.returncode:
        fail(result.stderr.strip() or result.stdout.strip() or f"Command failed: {arguments[0]}")
    return result


def sql(statement, database="postgres"):
    return run([
        bin_dir / "psql", "-X", "--no-password", "-A", "-t", "-v", "ON_ERROR_STOP=1",
        "-h", socket_dir, "-p", port, "-U", username, "-d", database, "-c", statement,
    ]).stdout.strip()


def running():
    owned_dir(data)
    if (data / "PG_VERSION").read_text().strip() != "18":
        fail("Existing data directory has another PostgreSQL major version")
    result = run([bin_dir / "pg_ctl", "-D", data, "status"], check=False)
    if result.returncode == 3:
        pid_file = data / "postmaster.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().splitlines()[0])
                if pid <= 1:
                    fail("Invalid PostgreSQL PID file")
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                fail("OS denied server status inspection; run with the same runtime permission as start")
            except (ValueError, IndexError):
                fail("Invalid PostgreSQL PID file")
            fail("pg_ctl and PID inspection disagree; refusing to manage this process")
        return False
    if result.returncode:
        fail(result.stderr.strip() or result.stdout.strip() or "Cannot determine server status")
    # Prove that the socket leads to this cluster before accepting or stopping it.
    if Path(sql("SHOW data_directory")).resolve() != data.resolve():
        fail("Socket points to another cluster; refusing to continue")
    if sql("SHOW listen_addresses") != "":
        fail("Unexpected TCP listener; this script manages Unix-socket-only servers")
    if sql("SELECT current_user") != username:
        fail("Unexpected database user")
    if not sql("SHOW server_version").startswith("18."):
        fail("Unexpected PostgreSQL major version")
    return True


owned_dir(runtime)
if not bin_dir.is_dir() or not (bin_dir / "pg_ctl").is_file():
    fail("Install the verified Postgres.app bundle in .runtime first; see docs/local-postgres.md")
if action in {"status", "stop", "check"} and not cluster.exists():
    print("stopped (cluster not initialized)")
    raise SystemExit(0 if action != "check" else 1)

# Advisory lock is released by the OS even if this script is interrupted.
lock_fd = os.open(runtime / "postgres18.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
if os.fstat(lock_fd).st_uid != uid:
    fail("Refusing foreign lock file")
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    fail("Another PostgreSQL management command is active for this project")

owned_dir(cluster, create=action == "start", marked=True)
owned_dir(socket_dir, create=action == "start", marked=True)

if action == "start":
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", bundle])
    if not data.exists():
        run([
            bin_dir / "initdb", "-D", data, "--encoding=UTF8", "--locale=C",
            "--auth-local=peer", "--auth-host=scram-sha-256",
        ])
    if not running():
        options = shlex.join([
            "-h", "", "-k", str(socket_dir), "-p", port,
            "-c", "unix_socket_permissions=0700", "-c", "max_connections=20",
            "-c", "shared_buffers=32MB",
        ])
        run([bin_dir / "pg_ctl", "-D", data, "-l", cluster / "server.log", "-w", "-t", "15", "-o", options, "start"])
        if not running():
            fail("Server did not start")
    for database in ("ara_dev", "ara_test"):
        if sql(f"SELECT 1 FROM pg_database WHERE datname = '{database}'") != "1":
            run([bin_dir / "createdb", "-h", socket_dir, "-p", port, "-U", username, database])
    print(f"running: PostgreSQL {sql('SHOW server_version')}; socket={socket_dir}; user={username}; databases=ara_dev,ara_test")
elif action == "stop":
    if running():
        run([bin_dir / "pg_ctl", "-D", data, "-w", "-t", "15", "-m", "fast", "stop"])
    print("stopped (data preserved)")
elif action == "status":
    print(f"running: socket={socket_dir}; user={username}" if running() else "stopped")
else:
    if not running():
        fail("Server is stopped")
    for database in ("ara_dev", "ara_test"):
        if sql("SELECT 1", database) != "1":
            fail(f"Connection check failed: {database}")
    print(f"PostgreSQL {sql('SHOW server_version')}: SELECT 1 passed for ara_dev and ara_test")
PY
