"""Native crash recovery across backup, SQL commit and schema receipt exchange."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_desktop_postgres_cluster import closed, home_at, ready
from test_desktop_postgres_cluster import tools as pg_tools
from test_desktop_postgres_cluster_recovery import wait_for_slot
from test_desktop_postgres_schema import prepared
from test_desktop_postgres_upgrade import bundles, job, payload, settled, stored

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native upgrade crash cuts")

PROGRAM = """
import os,sys,stat,time,json
from pathlib import Path
import psycopg
from test_desktop_postgres_upgrade import world,seeded,job
parent=Path(sys.argv[1]);step=sys.argv[2];manager=world(parent)
home,cluster=manager.__enter__();seeded(home,cluster)
root=home.path('root');journal=home.path('backups')/'schema';copies=home.path('backups')/'postgres'
original_sync=os.fsync
def crash_sync(fd):
 result=original_sync(fd)
 if stat.S_ISDIR(os.fstat(fd).st_mode):
  if step=='backup' and copies.exists() and list(copies.glob('*/backup.json')):
   os._exit(73)
  if step=='intent' and (journal/'upgrade.json').exists():
   os._exit(73)
  if (step=='swap' and (journal/'upgrade.json').exists()
      and (journal/'.ready.json.pending').exists()):
   current=json.loads((journal/'ready.json').read_bytes())
   previous=json.loads((journal/'.ready.json.pending').read_bytes())
   if current['revision'].startswith('0013_') and previous['revision'].startswith('0012_'):
    os._exit(73)
 return result
os.fsync=crash_sync
original_commit=psycopg.Connection.commit
def crash_commit(self):
 if step=='before_commit' and (journal/'upgrade.json').exists():
  if self.execute('SELECT version_num FROM alembic_version').fetchone()[0].startswith('0013_'):
   os._exit(73)
 result=original_commit(self)
 if step=='after_commit' and (journal/'upgrade.json').exists():
  with psycopg.connect(**dict(cluster.connection()),autocommit=True) as observer:
   if observer.execute('SELECT version_num FROM alembic_version').fetchone()[0].startswith('0013_'):
    os._exit(73)
 return result
psycopg.Connection.commit=crash_commit
original_unlink=os.unlink
def crash_unlink(path,*a,**kw):
 result=original_unlink(path,*a,**kw)
 if step=='cleanup' and str(path).endswith('upgrade.json'):
  os._exit(73)
 return result
os.unlink=crash_unlink
operation=job(home,cluster);operation.start();end=time.monotonic()+25
while operation.view().phase not in ('ready','failed','not_needed') and time.monotonic()<end:
 time.sleep(.01)
assert False,'Upgrade cutpoint not reached'
"""


@pytest.mark.parametrize(
    "step", ["backup", "intent", "before_commit", "after_commit", "swap", "cleanup"]
)
def test_upgrade_crash_reconciles_without_replacing_database(tmp_path, step):
    from ara.desktop.postgres_cluster import ClusterRuntime

    result = subprocess.run(
        [sys.executable, "-c", PROGRAM, str(tmp_path.resolve()), step],
        env={
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "PYTHONPATH": os.pathsep.join(
                (str(Path.cwd() / "src"), str(Path.cwd() / "tests/acceptance"))
            ),
        },
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 73, "Upgrade did not reach the requested crash cutpoint"
    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    wait_for_slot(root / "postgres")
    original = json.loads((root / "postgres" / "cluster.json").read_bytes())
    with home_at(root) as home:
        cluster = ready(ClusterRuntime(home, pg_tools()))
        try:
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).phase in ("ready", "not_needed")
            prepared(home, cluster)
            assert cluster.identity().database_oid == original["database_oid"]
            assert cluster.identity().system_identifier == original["system_identifier"]
            assert stored(home, cluster).current_data == payload()
            assert stored(home, cluster).title == "Synthetic upgrade"
            assert len(bundles(home)) == (2 if step == "backup" else 1)
            assert not (home.path("backups") / "schema" / "upgrade.json").exists()
            assert not (home.path("backups") / "schema" / ".ready.json.pending").exists()
        finally:
            closed(cluster)
