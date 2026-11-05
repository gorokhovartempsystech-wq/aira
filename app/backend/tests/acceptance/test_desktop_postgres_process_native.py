"""Disposable PostgreSQL lifetime/COMMIT/restart and parent-death acceptance."""

import json
import os
import pwd
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from test_desktop_postgres_process import api, done, until

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native macOS PostgreSQL lifetime")


@contextmanager
def prepared(tmp_path):
    from ara.desktop.postgres_profile import make_plan
    from ara.docx_analysis_worker.macos import acquire_owner

    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    root.mkdir(mode=0o700)
    owner = acquire_owner(root)
    binaries = Path.cwd() / ".runtime/Postgres.app/Contents/Versions/18/bin"
    plan = make_plan(
        target="macos-arm64",
        installation_id=uuid4(),
        postgres_root=str(root),
        system_user=pwd.getpwuid(os.geteuid()).pw_name,
    )
    initialization = api().OwnedCommand(owner, binaries / "initdb", plan.initdb_arguments, cwd=root)
    initialization.start()
    assert done(initialization).phase == "exited"
    os.rename(plan.staging_dir, plan.data_dir)
    for name, raw in plan.files.items():
        path = root / name
        path.write_bytes(raw)
        path.chmod(0o600)
    socket = Path(plan.socket_root)
    socket.mkdir(mode=0o700)
    try:
        yield owner, root, binaries, plan
    finally:
        owner.close()
        assert not (socket / ".s.PGSQL.5432").exists()
        socket.rmdir()


def connect(plan):
    end = time.monotonic() + 10
    while time.monotonic() < end:
        try:
            return psycopg.connect(**dict(plan.connection("postgres")))
        except psycopg.OperationalError:
            time.sleep(0.025)
    pytest.fail("Disposable PG did not accept its owner connection")


def test_commit_survives_pending_shutdown_and_owned_restart(tmp_path):
    with prepared(tmp_path) as (owner, root, binaries, plan):
        for first in (True, False):
            command = api().OwnedCommand(
                owner, binaries / "postgres", plan.postgres_arguments, cwd=root
            )
            conn = None
            command.start()
            try:
                conn = connect(plan)
                until(lambda: command.view().phase == "running")
                if first:
                    conn.execute("CREATE TABLE synthetic_pending_commit(value text NOT NULL)")
                    conn.execute("INSERT INTO synthetic_pending_commit VALUES ('saved once')")
                else:
                    assert conn.execute(
                        "SELECT value FROM synthetic_pending_commit"
                    ).fetchall() == [("saved once",)]
                assert command.shutdown(0.05) is False
                assert command.view().resources_pending
                conn.commit()
                conn.close()
                conn = None
                assert done(command).phase == "exited"
                assert command.view().returncode == 0
                assert command.shutdown(0)
            finally:
                if conn is not None:
                    conn.close()
                assert command.shutdown(5)


def test_parent_process_death_triggers_guardian_eof_and_keeps_committed_data(tmp_path):
    with prepared(tmp_path) as (owner, root, binaries, plan):
        owner.close()
        request = json.dumps(
            dict(
                root=str(root),
                binary=str(binaries / "postgres"),
                arguments=plan.postgres_arguments,
                connection=dict(plan.connection("postgres")),
            )
        )
        program = (
            "import os,sys,json,time,psycopg\nfrom pathlib import Path\n"
            "from ara.docx_analysis_worker.macos import acquire_owner\n"
            "from ara.desktop.postgres_process import OwnedCommand\n"
            "v=json.loads(sys.stdin.read());r=Path(v['root']);o=acquire_owner(r)\n"
            "c=OwnedCommand(o,Path(v['binary']),tuple(v['arguments']),cwd=r);c.start()\n"
            "end=time.monotonic()+10\n"
            "while time.monotonic()<end:\n"
            " try:\n  connection=psycopg.connect(**v['connection']);break\n"
            " except psycopg.OperationalError: time.sleep(.025)\n"
            "else: raise AssertionError()\n"
            "connection.execute('CREATE TABLE synthetic_parent_crash(value int NOT NULL)')\n"
            "connection.execute('INSERT INTO synthetic_parent_crash VALUES (73)')\n"
            "connection.commit()\nos._exit(73)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            input=request.encode(),
            capture_output=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONPATH": str(Path.cwd() / "src")},
            timeout=15,
        )
        assert result.returncode == 73

        from ara.docx_analysis_worker.macos import MacRuntimeError, acquire_owner

        resumed = acquire_owner(root)
        try:

            def available():
                try:
                    slot = resumed.reserve_slot()
                except MacRuntimeError as error:
                    assert error.code == "runtime_busy"
                    return False
                return resumed.release_slot(slot)

            until(available)
            command = api().OwnedCommand(
                resumed, binaries / "postgres", plan.postgres_arguments, cwd=root
            )
            connection = None
            command.start()
            try:
                connection = connect(plan)
                assert connection.execute(
                    "SELECT value FROM synthetic_parent_crash"
                ).fetchall() == [(73,)]
            finally:
                if connection is not None:
                    connection.close()
                assert command.shutdown(5)
            assert command.view().returncode == 0
        finally:
            resumed.close()
