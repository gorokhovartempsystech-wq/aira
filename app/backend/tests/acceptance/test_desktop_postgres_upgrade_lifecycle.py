"""Shared migration ownership, Stop and process-local handle checks."""

import copy
import os
import pickle
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from alembic import command
from test_desktop_postgres_cluster_recovery import wait_for_slot
from test_desktop_postgres_schema import job as schema_job
from test_desktop_postgres_schema import reject as schema_reject
from test_desktop_postgres_schema import settled as schema_settled
from test_desktop_postgres_upgrade import (
    V12,
    execute,
    job,
    reject,
    seeded,
    settled,
    stored,
    upgraded,
    world,
)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native upgrade lifecycle")


@pytest.mark.parametrize("first", ["schema", "upgrade"])
def test_schema_and_upgrade_share_process_exclusion_and_stop_safely(tmp_path, monkeypatch, first):
    entered, release = threading.Event(), threading.Event()
    original = command.upgrade

    def pause(*args, **kwargs):
        original(*args, **kwargs)
        entered.set()
        assert release.wait(10)

    second = tmp_path / "second"
    second.mkdir()
    with world(tmp_path) as (home, cluster), world(second) as (other_home, other_cluster):
        if first == "upgrade":
            before, _ = seeded(home, cluster)
            operation = job(home, cluster)
            blocked = schema_job(other_home, other_cluster)
        else:
            operation = schema_job(home, cluster)
            blocked = job(other_home, other_cluster)
        with monkeypatch.context() as patch:
            patch.setattr(command, "upgrade", pause)
            operation.start()
            try:
                assert entered.wait(10)
                if first == "upgrade":
                    schema_reject("schema_busy", blocked.start)
                else:
                    reject("upgrade_busy", blocked.start)
                assert not operation.shutdown(0.01)
            finally:
                release.set()
            state = settled(operation) if first == "upgrade" else schema_settled(operation)
            assert state.phase == "closed" and state.error_code is None
        if first == "upgrade":
            assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V12,)]
            assert stored(home, cluster) == before
            upgraded(home, cluster)
            assert stored(home, cluster) == before


def test_pid_and_copy_checks_precede_inherited_mutex(tmp_path, monkeypatch):
    with world(tmp_path) as (home, cluster):
        operation = job(home, cluster)
        for call in (
            lambda: copy.copy(operation),
            lambda: copy.deepcopy(operation),
            lambda: pickle.dumps(operation),
        ):
            with pytest.raises(TypeError):
                call()
        pid = os.getpid()
        with monkeypatch.context() as patch:
            patch.setattr(os, "getpid", lambda: pid + 1)
            for call in (
                operation.start,
                operation.view,
                operation.shutdown,
                operation.result,
                operation.backup_path,
            ):
                reject("invalid_handle", call)
        assert operation.shutdown(0)


ISOLATED = """
import sys,time,threading
from pathlib import Path
from sqlalchemy.engine import Connection
from test_desktop_postgres_upgrade import world,job
from test_desktop_postgres_schema import job as schema_job
from ara.desktop.postgres_schema import SchemaError
parent=Path(sys.argv[1]);manager=world(parent);home,cluster=manager.__enter__()
operation=job(home,cluster)
"""


@pytest.mark.parametrize("fault", ["thread", "thread_after", "sql_close"])
def test_unknown_upgrade_outcome_also_blocks_schema_job(tmp_path, fault):
    source = {
        "thread": """
def broken(self,*a,**kw):raise RuntimeError('SYNTHETIC_PRIVATE')
threading.Thread.__init__=broken
""",
        "thread_after": """
original=threading.Thread.start
def broken(self):
 original(self);self.join(10);raise RuntimeError('SYNTHETIC_PRIVATE')
threading.Thread.start=broken
""",
        "sql_close": """
original=Connection.close
def broken(self):
 original(self);raise RuntimeError('SYNTHETIC_PRIVATE')
Connection.close=broken
""",
    }[fault]
    ending = """
operation.start();end=time.monotonic()+20
while operation.view().phase!='failed' and time.monotonic()<end:time.sleep(.01)
assert operation.view().phase=='failed' and operation.view().resources_pending
assert not operation.shutdown(0)
try:schema_job(home,cluster).start()
except SchemaError as error:assert error.code=='schema_busy'
else:raise AssertionError('Unknown upgrade released shared migration owner')
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", ISOLATED + source + ending, str(tmp_path.resolve())],
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "PYTHONPATH": os.pathsep.join(
                (str(Path.cwd() / "src"), str(Path.cwd() / "tests/acceptance"))
            ),
        },
        capture_output=True,
        timeout=35,
    )
    assert result.returncode == 0 and result.stdout == b"ok\n", "Shared cleanup quarantine failed"
    wait_for_slot(tmp_path.resolve() / "SYNTHETIC_PRIVATE" / "postgres")
