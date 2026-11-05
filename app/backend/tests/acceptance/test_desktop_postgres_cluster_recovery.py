"""Crash cutpoints retain published identity and never overwrite existing cluster data."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_desktop_postgres_cluster import api, closed, home_at, ready, tools

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native macOS cluster recovery")


PREFIX = """
import os,sys,stat,time,platform
from pathlib import Path
import psycopg
from ara.desktop.data_home import open_home
from ara.desktop.postgres_cluster import ClusterRuntime,PgTools
from ara.desktop.postgres_process import OwnedCommand
root=Path(sys.argv[1]);step=sys.argv[2]
home=open_home(root);pg=root/'postgres'
binaries=Path.cwd()/'.runtime/Postgres.app/Contents/Versions/18/bin'
tools=PgTools('macos-arm64' if platform.machine()=='arm64' else 'macos-x86_64',
              binaries/'postgres',binaries/'initdb',binaries/'pg_controldata')
original_sync=os.fsync
def crash_sync(fd):
 result=original_sync(fd)
 if stat.S_ISDIR(os.fstat(fd).st_mode) and pg.exists():
  names={p.name for p in pg.iterdir()}
  if step=='intent' and 'initialization.json' in names and '.data18.pending' not in names:
   os._exit(73)
  if step=='prepared' and 'prepared.json' in names and '.data18.pending' in names:
   os._exit(73)
  if step=='data' and 'data18' in names and 'cluster.json' not in names:
   os._exit(73)
  if step=='final' and 'cluster.json' in names:
   os._exit(73)
 return result
os.fsync=crash_sync
original_output=OwnedCommand.stdout
def crash_output(self):
 output=original_output(self)
 if step=='stage' and (pg/'.data18.pending').exists() and not (pg/'prepared.json').exists():
  os._exit(73)
 return output
OwnedCommand.stdout=crash_output
original_execute=psycopg.Connection.execute
def crash_execute(self,query,*a,**kw):
 result=original_execute(self,query,*a,**kw)
 query_text=query.as_string(self) if hasattr(query,'as_string') else str(query)
 if step=='ddl' and query_text.strip().upper().startswith('CREATE DATABASE'):
  os._exit(73)
 return result
psycopg.Connection.execute=crash_execute
original_unlink=os.unlink
def crash_unlink(path,*a,**kw):
 result=original_unlink(path,*a,**kw)
 if step=='cleanup' and str(path).endswith('prepared.json'):
  os._exit(73)
 return result
os.unlink=crash_unlink
runtime=ClusterRuntime(home,tools);runtime.start()
end=time.monotonic()+20
while time.monotonic()<end:
 if runtime.view().phase in ('ready','failed'):break
 time.sleep(.01)
assert False,'Expected native crash cutpoint was not reached'
"""


def wait_for_slot(root):
    from ara.docx_analysis_worker.macos import MacRuntimeError, acquire_owner

    end = time.monotonic() + 10
    while time.monotonic() < end:
        owner = None
        try:
            owner = acquire_owner(root)
            slot = owner.reserve_slot()
            assert owner.release_slot(slot)
            return
        except MacRuntimeError as error:
            assert error.code == "runtime_busy"
        finally:
            if owner is not None:
                owner.close()
        time.sleep(0.025)
    pytest.fail("Crashed initializer still owns native resources")


@pytest.mark.parametrize("step", ["intent", "stage", "prepared", "data", "ddl", "final", "cleanup"])
def test_native_crash_restart_finishes_same_initialization_or_preserves_partial(tmp_path, step):
    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    result = subprocess.run(
        [sys.executable, "-c", PREFIX, str(root), step],
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=25,
    )
    assert result.returncode == 73, "Initializer did not reach the requested crash cutpoint"
    wait_for_slot(root / "postgres")
    expected = None
    for name in ("cluster.json", "prepared.json"):
        path = root / "postgres" / name
        if path.exists():
            expected = json.loads(path.read_bytes())["system_identifier"]
            break
    with home_at(root) as home:
        runtime = ready(api().ClusterRuntime(home, tools()))
        try:
            if expected is not None:
                assert runtime.identity().system_identifier == expected
            if step == "stage":
                retained = list((root / "postgres").glob("failed-init-*"))
                assert len(retained) == 1 and (retained[0] / "PG_VERSION").read_bytes() == b"18\n"
            assert not (root / "postgres" / "initialization.json").exists()
            assert not (root / "postgres" / "prepared.json").exists()
        finally:
            closed(runtime)
