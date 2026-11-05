"""In-flight connection admission and unknown DBAPI cleanup remain owned."""

import os
import subprocess
import sys
import threading
from pathlib import Path

import psycopg
import pytest
from test_desktop_database import api, bound, reject
from test_desktop_postgres_cluster_recovery import wait_for_slot

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native database lifetime")


def test_stop_during_native_connect_waits_and_never_hands_connection_to_caller(
    tmp_path, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    observed, outcome = [], []
    original = psycopg.Connection.connect.__func__

    def pause(cls, *args, **kwargs):
        raw = original(cls, *args, **kwargs)
        observed.append(raw)
        entered.set()
        assert release.wait(10)
        return raw

    with bound(tmp_path) as (_, _, _, source):
        engine = source.document_runtime().engine

        def connect():
            try:
                with engine.connect():
                    outcome.append("unexpected_connection")
            except api().DatabaseError as error:
                outcome.append(error.code)

        with monkeypatch.context() as patch:
            patch.setattr(psycopg.Connection, "connect", classmethod(pause))
            thread = threading.Thread(target=connect)
            thread.start()
            try:
                assert entered.wait(10)
                assert source.view().connecting == 1
                assert not source.shutdown(0.01)
                reject("invalid_handle", engine.connect)
            finally:
                release.set()
                thread.join(10)
            assert not thread.is_alive()
        assert outcome == ["invalid_handle"]
        assert len(observed) == 1 and observed[0].closed
        assert source.shutdown(0)
        assert source.view().connections == source.view().connecting == 0


PROGRAM = """
import sys,psycopg
from pathlib import Path
from test_desktop_postgres_schema import world,prepared
from ara.desktop.database import bind_database,DatabaseError
manager=world(Path(sys.argv[1]));home,cluster=manager.__enter__();schema=prepared(home,cluster)
source=bind_database(home,cluster,schema=schema);engine=source.document_runtime().engine
connection=engine.connect();raw=connection.connection.driver_connection
original=psycopg.Connection.close;calls=[]
def unknown(self):
 if self is raw:
  calls.append(True);original(self);raise RuntimeError('SYNTHETIC_PRIVATE')
 return original(self)
psycopg.Connection.close=unknown
try:connection.close()
except DatabaseError as error:assert error.code=='cleanup_unknown'
assert raw.closed and calls==[True]
state=source.view()
assert state.phase=='failed' and state.error_code=='cleanup_unknown' and state.resources_pending
assert not source.shutdown(0)
try:raw.close()
except DatabaseError as error:assert error.code=='cleanup_unknown'
else:raise AssertionError('Repeated native close was allowed')
assert calls==[True]
try:bind_database(home,cluster,schema=schema)
except DatabaseError as error:assert error.code=='database_busy'
else:raise AssertionError('Unknown close released database source claim')
print('ok')
"""


def test_close_after_driver_finish_is_still_unknown_and_never_retried(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path.resolve())],
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
    assert result.returncode == 0 and result.stdout == b"ok\n", "Unknown SQL cleanup was released"
    assert b"SYNTHETIC_PRIVATE" not in result.stderr
    wait_for_slot(tmp_path.resolve() / "SYNTHETIC_PRIVATE" / "postgres")
