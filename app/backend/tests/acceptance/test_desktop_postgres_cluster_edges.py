"""Review of damaged metadata, identity substitution and unknown cleanup outcomes."""

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from test_desktop_postgres_cluster import api, closed, home_at, ready, reject, tools, wait
from test_desktop_postgres_cluster_recovery import wait_for_slot

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native cluster review")


@pytest.mark.parametrize(
    "case", ["oid", "system", "installation", "version", "config", "missing_data", "record_temp"]
)
def test_published_installation_never_replaced_on_damage(tmp_path, case):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        runtime = ready(api().ClusterRuntime(home, tools()))
        original = runtime.identity()
        closed(runtime)
        root = home.path("postgres")
        marker = root / "cluster.json"
        record = json.loads(marker.read_bytes())
        if case == "oid":
            record["database_oid"] += 1
        elif case == "system":
            record["system_identifier"] = str(int(record["system_identifier"]) + 1)
        elif case == "installation":
            record["installation_id"] = "00000000-0000-4000-8000-000000000001"
        elif case == "version":
            (root / "data18" / "PG_VERSION").write_bytes(b"17\n")
        elif case == "config":
            (root / "pg_hba.conf").write_bytes(b"preserve unexpected config\n")
        elif case == "missing_data":
            (root / "data18").rename(tmp_path / "retained_database")
        elif case == "record_temp":
            (root / ".cluster.json.pending").write_bytes(marker.read_bytes())
            (root / ".cluster.json.pending").chmod(0o600)
        if case in {"oid", "system", "installation"}:
            marker.write_text(json.dumps(record))
        preserved = marker.read_bytes()
        runtime = api().ClusterRuntime(home, tools())
        runtime.start()
        assert wait(runtime).error_code == "cluster_recovery_required"
        closed(runtime)
        assert marker.read_bytes() == preserved
        assert not (root / "initialization.json").exists()
        assert not (root / ".data18.pending").exists()
        if case == "missing_data":
            assert not (root / "data18").exists()
            assert (tmp_path / "retained_database" / "PG_VERSION").read_bytes() == b"18\n"
        assert original.postgres_major == 18


def test_partial_intent_temp_only_is_repairable(tmp_path):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        temp = home.path("postgres") / ".initialization.json.pending"
        temp.write_bytes(b'{"schema_version":')
        temp.chmod(0o600)
        runtime = ready(api().ClusterRuntime(home, tools()))
        closed(runtime)
        assert not temp.exists()


@pytest.mark.parametrize("kind", ["prepared", "cluster"])
def test_complete_journal_temp_resumes_same_database(tmp_path, kind):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        runtime = ready(api().ClusterRuntime(home, tools()))
        identity = runtime.identity()
        closed(runtime)
        root = home.path("postgres")
        initial = dict(
            schema_version="aira-pg-initialization/1",
            installation_id=str(identity.installation_id),
            target=tools().target,
        )
        prepared = dict(
            initial,
            schema_version="aira-pg-prepared/1",
            system_identifier=identity.system_identifier,
        )
        for name, record in (("initialization.json", initial), ("prepared.json", prepared)):
            (root / name).write_text(json.dumps(record))
            (root / name).chmod(0o600)
        if kind == "prepared":
            (root / "cluster.json").unlink()
            (root / "prepared.json").rename(root / ".prepared.json.pending")
        else:
            (root / "cluster.json").rename(root / ".cluster.json.pending")
        runtime = ready(api().ClusterRuntime(home, tools()))
        assert runtime.identity() == identity
        closed(runtime)
        assert not (root / ("." + kind + ".json.pending")).exists()


def test_stop_after_prepared_preserves_proof_and_reopens(tmp_path, monkeypatch):
    from ara.desktop.postgres_cluster._filesystem import Filesystem

    entered, release = threading.Event(), threading.Event()
    original = Filesystem.publish

    def gate(self, name, raw):
        original(self, name, raw)
        if name == "prepared.json":
            entered.set()
            assert release.wait(10)

    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        runtime = api().ClusterRuntime(home, tools())
        with monkeypatch.context() as patch:
            patch.setattr(Filesystem, "publish", gate)
            runtime.start()
            try:
                assert entered.wait(10)
                proof = json.loads((home.path("postgres") / "prepared.json").read_bytes())
                assert not runtime.shutdown(0.01)
                reject("invalid_handle", runtime.connection)
            finally:
                release.set()
                closed(runtime)
        runtime = ready(api().ClusterRuntime(home, tools()))
        assert runtime.identity().system_identifier == proof["system_identifier"]
        closed(runtime)


ISOLATED = """
import sys,time,threading,os,platform
from pathlib import Path
import psycopg
from ara.desktop.data_home import open_home
from ara.desktop.postgres_cluster import ClusterRuntime,PgTools,ClusterError
from ara.desktop.postgres_cluster._backend import Backend
from ara.desktop.postgres_cluster._filesystem import Filesystem
root=Path(sys.argv[1]);home=open_home(root)
bin=Path.cwd()/'.runtime/Postgres.app/Contents/Versions/18/bin'
tools=PgTools('macos-arm64' if platform.machine()=='arm64' else 'macos-x86_64',
bin/'postgres',bin/'initdb',bin/'pg_controldata')
runtime=ClusterRuntime(home,tools)
"""


@pytest.mark.parametrize("fault", ["thread", "thread_after", "sql_close", "fd_close"])
def test_unknown_outcomes_remain_claimed_until_process_exit(tmp_path, fault):
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
original=psycopg.Connection.close
def broken(self):
 original(self);raise RuntimeError('SYNTHETIC_PRIVATE')
psycopg.Connection.close=broken
""",
        "fd_close": """
original=Filesystem.close_fd
def broken(self,fd):
 original(self,fd)
 if fd is not None and fd==getattr(self,'review_root',None):
  raise RuntimeError('SYNTHETIC_PRIVATE')
Filesystem.close_fd=broken
original_run=Backend.run
def stopped(self):
 original_run(self)
 self.fs.review_root=self.fs.fd
Backend.run=stopped
""",
    }[fault]
    ending = """
runtime.start()
end=time.monotonic()+15
while runtime.view().phase not in ('ready','failed') and time.monotonic()<end:time.sleep(.01)
if runtime.view().phase=='ready':runtime.shutdown(.5)
end=time.monotonic()+5
while runtime.view().phase!='failed' and time.monotonic()<end:time.sleep(.01)
assert runtime.view().phase=='failed' and runtime.view().resources_pending
assert not runtime.shutdown(0)
assert 'SYNTHETIC_PRIVATE' not in repr(runtime.view())
try:ClusterRuntime(home,tools).start()
except ClusterError as error:assert error.code=='cluster_busy'
else:raise AssertionError('Unknown cleanup released the cluster')
print('ok')
"""
    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    result = subprocess.run(
        [sys.executable, "-c", ISOLATED + source + ending, str(root)],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONPATH": str(Path.cwd() / "src")},
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0 and result.stdout == b"ok\n", "Cleanup quarantine failed"
    if (root / "postgres" / "runtime.owner").exists():
        wait_for_slot(root / "postgres")


def test_startup_deadline_before_mutation(tmp_path, monkeypatch):
    from ara.docx_analysis_worker.macos import DarwinClock

    times = iter((0, 120_000_000_001))
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        monkeypatch.setattr(DarwinClock, "now_ns", lambda self: next(times))
        runtime = api().ClusterRuntime(home, tools())
        runtime.start()
        assert wait(runtime).error_code == "startup_timeout"
        closed(runtime)
        assert list(home.path("postgres").iterdir()) == []


@pytest.mark.parametrize(
    "name", ["PGREQUIREPEER", "PGMINPROTOCOLVERSION", "PGMAXPROTOCOLVERSION", "PGLOCALEDIR"]
)
def test_remaining_documented_libpq_defaults_fail_before_mutation(tmp_path, monkeypatch, name):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        monkeypatch.setenv(name, "SYNTHETIC_PRIVATE")
        runtime = api().ClusterRuntime(home, tools())
        runtime.start()
        assert wait(runtime).error_code == "cluster_unavailable"
        closed(runtime)
        assert list(home.path("postgres").iterdir()) == []


def test_database_substitution_between_observation_and_application_connection(
    tmp_path, monkeypatch
):
    import psycopg

    from ara.desktop.postgres_cluster._backend import Backend

    original = Backend.connect

    def substitute(self, database, **kwargs):
        if database == "aira":
            with psycopg.connect(**dict(self.plan.connection("postgres")), autocommit=True) as conn:
                conn.execute("ALTER DATABASE aira RENAME TO synthetic_preserved_database")
                conn.execute(
                    "CREATE DATABASE aira OWNER aira_local ENCODING 'UTF8' "
                    "LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0"
                )
        return original(self, database, **kwargs)

    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        runtime = ready(api().ClusterRuntime(home, tools()))
        closed(runtime)
        record = (home.path("postgres") / "cluster.json").read_bytes()
        with monkeypatch.context() as patch:
            patch.setattr(Backend, "connect", substitute)
            runtime = api().ClusterRuntime(home, tools())
            runtime.start()
            try:
                assert wait(runtime).error_code == "cluster_recovery_required"
            finally:
                closed(runtime)
        assert (home.path("postgres") / "cluster.json").read_bytes() == record
