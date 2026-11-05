"""Known pre-connect refusal versus an unknown native creation outcome."""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from test_desktop_database import bound, reject
from test_desktop_postgres_cluster_recovery import wait_for_slot

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native SQL bridge review")


@pytest.mark.parametrize("fault", ["metadata", "operational"])
def test_known_refusal_before_returned_connection_does_not_invent_pending_native_io(
    tmp_path, monkeypatch, fault
):
    from ara.desktop.postgres_cluster import ClusterError, ClusterRuntime

    def unavailable(*args, **kwargs):
        if fault == "metadata":
            raise ClusterError("invalid_handle")
        raise psycopg.OperationalError("SYNTHETIC_PRIVATE")

    with bound(tmp_path) as (_, _, _, source):
        engine = source.document_runtime().engine
        with monkeypatch.context() as patch:
            if fault == "metadata":
                patch.setattr(ClusterRuntime, "connection", unavailable)
            else:
                patch.setattr(psycopg.Connection, "connect", classmethod(unavailable))
            reject(
                "invalid_handle" if fault == "metadata" else "database_unavailable", engine.connect
            )
        assert source.view().phase == "ready"
        assert source.view().connections == source.view().connecting == 0
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1


PROGRAM = """
import sys,psycopg
from pathlib import Path
from test_desktop_postgres_schema import world,prepared
from ara.desktop.database import bind_database,DatabaseError
manager=world(Path(sys.argv[1]));home,cluster=manager.__enter__();schema=prepared(home,cluster)
source=bind_database(home,cluster,schema=schema);engine=source.document_runtime().engine
original=psycopg.Connection.connect.__func__;retained=[]
def unknown(cls,*args,**kwargs):
 retained.append(original(cls,*args,**kwargs))
 if sys.argv[2]=='typed':raise DatabaseError('cleanup_unknown')
 raise RuntimeError('SYNTHETIC_PRIVATE')
psycopg.Connection.connect=classmethod(unknown)
try:engine.connect()
except DatabaseError as error:assert error.code=='cleanup_unknown'
else:raise AssertionError('Unknown native creation succeeded')
assert retained and source.view().phase=='failed' and source.view().resources_pending
assert not source.shutdown(0)
try:bind_database(home,cluster,schema=schema)
except DatabaseError as error:assert error.code=='database_busy'
else:raise AssertionError('Unknown creation released its claim')
print('ok')
"""


@pytest.mark.parametrize("kind", ["ordinary", "typed"])
def test_unknown_native_creation_keeps_strong_pending_claim(tmp_path, kind):
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path.resolve()), kind],
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "PYTHONPATH": os.pathsep.join(
                (str(Path.cwd() / "src"), str(Path.cwd() / "tests/acceptance"))
            ),
        },
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0 and result.stdout == b"ok\n", (
        "Unknown native creation lost ownership"
    )
    assert b"SYNTHETIC_PRIVATE" not in result.stderr
    wait_for_slot(tmp_path.resolve() / "SYNTHETIC_PRIVATE" / "postgres")
