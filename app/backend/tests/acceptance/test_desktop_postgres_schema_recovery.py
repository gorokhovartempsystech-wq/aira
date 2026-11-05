"""Crash cuts around schema COMMIT and durable provenance, with native PG recovery."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_desktop_postgres_cluster import closed, home_at, ready, tools
from test_desktop_postgres_cluster_recovery import wait_for_slot
from test_desktop_postgres_schema import V13, prepared

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native schema crash recovery")

PROGRAM = """
import os,sys,time,stat,platform
from pathlib import Path
import psycopg
from ara.desktop.data_home import open_home
from ara.desktop.postgres_cluster import ClusterRuntime,PgTools
from ara.desktop.postgres_schema import SchemaPreparation
root=Path(sys.argv[1]);step=sys.argv[2];home=open_home(root)
bin=Path.cwd()/'.runtime/Postgres.app/Contents/Versions/18/bin'
tools=PgTools('macos-arm64' if platform.machine()=='arm64' else 'macos-x86_64',
bin/'postgres',bin/'initdb',bin/'pg_controldata')
cluster=ClusterRuntime(home,tools);cluster.start();end=time.monotonic()+20
while cluster.view().phase not in ('ready','failed') and time.monotonic()<end:time.sleep(.01)
assert cluster.view().phase=='ready'
journal=root/'backups'/'schema'
original_sync=os.fsync
def crash_sync(fd):
 result=original_sync(fd)
 if stat.S_ISDIR(os.fstat(fd).st_mode):
  if step=='intent' and (journal/'initializing.json').exists():os._exit(73)
  if step=='ready' and (journal/'ready.json').exists():os._exit(73)
 return result
os.fsync=crash_sync
original_commit=psycopg.Connection.commit
def crash_commit(self):
 if step=='before_commit' and (journal/'initializing.json').exists():
  if self.execute("SELECT to_regclass('public.docx_documents')").fetchone()[0]:os._exit(73)
 result=original_commit(self)
 if step=='after_commit' and (journal/'initializing.json').exists():
  with psycopg.connect(**dict(cluster.connection()),autocommit=True) as observer:
   if observer.execute("SELECT to_regclass('public.docx_documents')").fetchone()[0]:os._exit(73)
 return result
psycopg.Connection.commit=crash_commit
original_unlink=os.unlink
def crash_unlink(path,*a,**kw):
 result=original_unlink(path,*a,**kw)
 if step=='cleanup' and str(path).endswith('initializing.json'):os._exit(73)
 return result
os.unlink=crash_unlink
operation=SchemaPreparation(home,cluster,migrations=Path.cwd()/'migrations');operation.start()
end=time.monotonic()+20
while operation.view().phase not in ('ready','failed') and time.monotonic()<end:time.sleep(.01)
assert False,'Schema cutpoint not reached'
"""


@pytest.mark.parametrize("step", ["intent", "before_commit", "after_commit", "ready", "cleanup"])
def test_schema_crash_reconciles_same_database_and_identity(tmp_path, step):
    from ara.desktop.postgres_cluster import ClusterRuntime

    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(root), step],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONPATH": str(Path.cwd() / "src")},
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 73, "Schema did not reach the requested crash cutpoint"
    wait_for_slot(root / "postgres")
    before = json.loads((root / "postgres" / "cluster.json").read_bytes())
    with home_at(root) as home:
        cluster = ready(ClusterRuntime(home, tools()))
        try:
            operation = prepared(home, cluster)
            assert operation.receipt().revision == V13
            assert operation.receipt().database_oid == before["database_oid"]
            assert operation.receipt().system_identifier == before["system_identifier"]
            assert operation.receipt().user_id == home.identity().user_id
            assert not (root / "backups" / "schema" / "initializing.json").exists()
        finally:
            closed(cluster)
