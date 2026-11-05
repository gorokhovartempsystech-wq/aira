"""Real macOS PG18 profile smoke in a new disposable cluster, not the dev cluster."""

import importlib
import os
import pwd
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS PG profile gate")


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    module = importlib.import_module("ara.desktop.postgres_profile")
    binaries = Path.cwd() / ".runtime/Postgres.app/Contents/Versions/18/bin"
    assert (binaries / "postgres").is_file(), "Verified PG18 fixture runtime is required"
    root = tmp_path_factory.mktemp("pg-profile").resolve() / "Synthetic O'Brien postgres"
    root.mkdir(mode=0o700)
    plan = module.make_plan(
        target="macos-arm64",
        installation_id=uuid4(),
        postgres_root=str(root),
        system_user=pwd.getpwuid(os.geteuid()).pw_name,
    )
    child_env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "TZ": "UTC"}
    result = subprocess.run(
        [str(binaries / "initdb"), *plan.initdb_arguments],
        env=child_env,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, "Disposable initdb profile failed"
    os.rename(plan.staging_dir, plan.data_dir)
    control = subprocess.run(
        [str(binaries / "pg_controldata"), plan.data_dir],
        env=child_env,
        capture_output=True,
        timeout=5,
    )
    assert control.returncode == 0
    identifier = re.search(rb"^Database system identifier:\s+([0-9]+)$", control.stdout, re.M)
    assert identifier is not None
    expected = identifier[1].decode("ascii")
    for name, raw in plan.files.items():
        target = root / name
        target.write_bytes(raw)
        target.chmod(0o600)
    socket_root = Path(plan.socket_root)
    socket_root.mkdir(mode=0o700)
    process = None
    try:
        process = subprocess.Popen(
            [str(binaries / "postgres"), *plan.postgres_arguments],
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            assert process.poll() is None, "Disposable foreground PG exited before readiness"
            try:
                with psycopg.connect(**dict(plan.connection("postgres")), autocommit=True) as conn:
                    conn.execute("CREATE DATABASE aira")
                break
            except psycopg.OperationalError:
                time.sleep(0.025)
        else:
            pytest.fail("Disposable PG readiness timed out")
        yield module, plan, expected
    finally:
        if process is not None:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=10) == 0, "Disposable PG smart shutdown failed"
        assert not (socket_root / ".s.PGSQL.5432").exists()
        socket_root.rmdir()


def test_native_configuration_and_observation_match(cluster):
    module, plan, identifier = cluster
    with psycopg.connect(**dict(plan.connection()), autocommit=True) as conn:
        actual = conn.execute(module.OBSERVATION_SQL).fetchone()[0]
        assert module.check_observation(plan, actual, expected_system_identifier=identifier) is None
        assert conn.execute("SHOW listen_addresses").fetchone()[0] == ""
        assert conn.execute("SHOW data_checksums").fetchone()[0] == "on"
        assert (
            conn.execute("SELECT error FROM pg_hba_file_rules WHERE error IS NOT NULL").fetchall()
            == []
        )
        assert (
            conn.execute(
                "SELECT error FROM pg_ident_file_mappings WHERE error IS NOT NULL"
            ).fetchall()
            == []
        )
        conn.execute("CREATE TABLE synthetic_profile_probe(value text NOT NULL)")
        conn.execute("INSERT INTO synthetic_profile_probe VALUES ('preserved synthetic text')")
        assert conn.execute("SELECT value FROM synthetic_profile_probe").fetchone()[0] == (
            "preserved synthetic text"
        )
        with pytest.raises(module.ProfileError, match="state"):
            module.check_observation(plan, actual, expected_system_identifier="42")


def test_native_hba_rejects_other_role_and_database(cluster):
    _, plan, _ = cluster
    other_role = dict(plan.connection()) | {"user": "other_synthetic_role"}
    other_database = dict(plan.connection()) | {"dbname": "template1"}
    for parameters in (other_role, other_database):
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(**parameters)
