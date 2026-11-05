"""Review of cancellation, global Alembic ownership and uncertain cleanup."""

import subprocess
import sys
import threading
from pathlib import Path

import pytest
from test_desktop_postgres_cluster_recovery import wait_for_slot
from test_desktop_postgres_schema import (
    execute,
    job,
    prepared,
    reject,
    relations,
    settled,
    world,
)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native schema lifecycle review")


def test_stop_in_migration_rolls_back_and_serializes_other_clusters(tmp_path, monkeypatch):
    from alembic import command

    entered, release = threading.Event(), threading.Event()
    original = command.upgrade

    def paused(*args, **kwargs):
        original(*args, **kwargs)
        entered.set()
        assert release.wait(10)

    second = tmp_path / "second"
    second.mkdir()
    with world(tmp_path) as (home, cluster), world(second) as (other_home, other_cluster):
        operation = job(home, cluster)
        with monkeypatch.context() as patch:
            patch.setattr(command, "upgrade", paused)
            operation.start()
            try:
                assert entered.wait(10)
                assert not operation.shutdown(0.01)
                assert operation.view().resources_pending
                reject("invalid_handle", operation.receipt)
                reject("schema_busy", job(other_home, other_cluster).start)
            finally:
                release.set()
            assert settled(operation).phase == "closed"
        assert relations(cluster) == []
        assert (home.path("backups") / "schema" / "initializing.json").exists()
        assert not (home.path("backups") / "schema" / "ready.json").exists()
        prepared(home, cluster)
        prepared(other_home, other_cluster)


def test_failure_after_ddl_does_not_commit_partial_schema(tmp_path, monkeypatch):
    from alembic import command

    original = command.upgrade

    def failed(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC_PRIVATE failure after DDL")

    with world(tmp_path) as (home, cluster):
        with monkeypatch.context() as patch:
            patch.setattr(command, "upgrade", failed)
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "schema_unavailable"
        assert relations(cluster) == []
        prepared(home, cluster)
        assert execute(cluster, "SELECT count(*) FROM users") == [(1,)]


def test_pristine_partial_intent_is_recovered(tmp_path):
    with world(tmp_path) as (home, cluster):
        root = home.path("backups") / "schema"
        root.mkdir(mode=0o700)
        temp = root / ".initializing.json.pending"
        temp.write_bytes(b'{"schema_version":')
        temp.chmod(0o600)
        prepared(home, cluster)
        assert not temp.exists()
        assert (root / "ready.json").is_file()


def test_deadline_and_environment_fail_before_journal_mutation(tmp_path, monkeypatch):
    from ara.desktop.postgres_schema import _backend

    class Clock:
        def __init__(self):
            self.values = iter((0, 120_000_000_001))

        def now_ns(self):
            return next(self.values)

    with world(tmp_path) as (home, cluster):
        with monkeypatch.context() as patch:
            patch.setattr(_backend, "DarwinClock", Clock)
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "startup_timeout"
        assert list(home.path("backups").iterdir()) == []
        with monkeypatch.context() as patch:
            patch.setenv("PGSERVICE", "SYNTHETIC_PRIVATE")
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "schema_unavailable"
        assert list(home.path("backups").iterdir()) == []
        assert relations(cluster) == []


ISOLATED = """
import sys,os,time,threading,platform
from pathlib import Path
from sqlalchemy.engine import Connection,Engine
from ara.desktop.data_home import open_home
from ara.desktop.postgres_cluster import ClusterRuntime,PgTools
from ara.desktop.postgres_schema import SchemaPreparation,SchemaError
from ara.desktop.postgres_schema._backend import Backend
root=Path(sys.argv[1]);home=open_home(root)
bin=Path.cwd()/'.runtime/Postgres.app/Contents/Versions/18/bin'
tools=PgTools('macos-arm64' if platform.machine()=='arm64' else 'macos-x86_64',
bin/'postgres',bin/'initdb',bin/'pg_controldata')
cluster=ClusterRuntime(home,tools);cluster.start();end=time.monotonic()+20
while cluster.view().phase not in ('ready','failed') and time.monotonic()<end:time.sleep(.01)
assert cluster.view().phase=='ready'
migrations=Path.cwd()/'migrations'
operation=SchemaPreparation(home,cluster,migrations=migrations)
"""


@pytest.mark.parametrize("fault", ["thread", "thread_after", "sql_close", "engine_dispose"])
def test_unknown_cleanup_holds_process_claim(tmp_path, fault):
    source = {
        "thread": """
def broken(self,*a,**kw):raise RuntimeError('SYNTHETIC_PRIVATE')
threading.Thread.__init__=broken
""",
        "thread_after": """
Backend.run=lambda self:None
original=threading.Thread.start
def broken(self):
 original(self);self.join(5);raise RuntimeError('SYNTHETIC_PRIVATE')
threading.Thread.start=broken
""",
        "sql_close": """
original=Connection.close
def broken(self):
 original(self)
 if threading.current_thread().name=='aira-pg-schema':raise RuntimeError('SYNTHETIC_PRIVATE')
Connection.close=broken
""",
        "engine_dispose": """
original=Engine.dispose
def broken(self,*a,**kw):
 original(self,*a,**kw)
 if threading.current_thread().name=='aira-pg-schema':raise RuntimeError('SYNTHETIC_PRIVATE')
Engine.dispose=broken
""",
    }[fault]
    ending = """
operation.start();end=time.monotonic()+20
while operation.view().phase!='failed' and time.monotonic()<end:time.sleep(.01)
assert operation.view().phase=='failed' and operation.view().resources_pending
assert not operation.shutdown(0)
try:operation.receipt()
except SchemaError as error:assert error.code=='invalid_handle'
else:raise AssertionError('Unconfirmed cleanup issued ready')
try:SchemaPreparation(home,cluster,migrations=migrations).start()
except SchemaError as error:assert error.code=='schema_busy'
else:raise AssertionError('Unknown owner released process claim')
print('ok')
"""
    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    result = subprocess.run(
        [sys.executable, "-c", ISOLATED + source + ending, str(root)],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONPATH": str(Path.cwd() / "src")},
        capture_output=True,
        timeout=35,
    )
    assert result.returncode == 0 and result.stdout == b"ok\n", "Schema quarantine failed"
    wait_for_slot(root / "postgres")


@pytest.mark.parametrize("boundary", ["timeout", "stop"])
def test_success_is_not_published_after_deadline_or_stop_during_cleanup(
    tmp_path, monkeypatch, boundary
):
    from ara.desktop.postgres_schema._backend import Backend

    entered, release = threading.Event(), threading.Event()
    original = Backend.close

    def paused(self):
        clean = original(self)
        if boundary == "timeout":
            self.deadline = 0
        entered.set()
        assert release.wait(10)
        return clean

    with world(tmp_path) as (home, cluster):
        with monkeypatch.context() as patch:
            patch.setattr(Backend, "close", paused)
            operation = job(home, cluster)
            operation.start()
            try:
                assert entered.wait(10)
                reject("invalid_handle", operation.receipt)
                if boundary == "stop":
                    assert not operation.shutdown(0.01)
            finally:
                release.set()
            result = settled(operation)
            if boundary == "timeout":
                assert result.phase == "failed" and result.error_code == "startup_timeout"
            else:
                assert result.phase == "closed" and result.error_code is None
        # The completed transaction/receipt are preserved even though this attempt
        # was no longer allowed to issue a successful result to its caller.
        assert (home.path("backups") / "schema" / "ready.json").exists()
        prepared(home, cluster)
        assert execute(cluster, "SELECT count(*) FROM users") == [(1,)]


def test_advisory_contention_does_not_begin_initialization(tmp_path):
    import psycopg

    with world(tmp_path) as (home, cluster):
        with psycopg.connect(**dict(cluster.connection())) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(1095911745,170302)")
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "schema_busy"
            assert not (home.path("backups") / "schema" / "initializing.json").exists()
            connection.rollback()
        prepared(home, cluster)
