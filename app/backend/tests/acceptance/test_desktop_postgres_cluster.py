"""Persistent cluster acceptance on synthetic local data, never the developer cluster."""

import copy
import dataclasses
import importlib
import json
import os
import pickle
import platform
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native macOS cluster bootstrap")


def api():
    return importlib.import_module("ara.desktop.postgres_cluster")


def tools():
    binaries = Path.cwd() / ".runtime/Postgres.app/Contents/Versions/18/bin"
    return api().PgTools(
        "macos-arm64" if platform.machine() == "arm64" else "macos-x86_64",
        binaries / "postgres",
        binaries / "initdb",
        binaries / "pg_controldata",
    )


def wait(runtime, phases=("ready", "failed"), timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        view = runtime.view()
        if view.phase in phases:
            return view
        time.sleep(0.02)
    pytest.fail("Synthetic cluster did not reach the expected state")


def ready(runtime):
    runtime.start()
    view = wait(runtime)
    assert view.phase == "ready" and view.error_code is None, view
    return runtime


def closed(runtime):
    end = time.monotonic() + 12
    while time.monotonic() < end:
        if runtime.shutdown(0.2):
            return
    pytest.fail("Synthetic cluster resources did not close")


def reject(code, call):
    with pytest.raises(api().ClusterError) as error:
        call()
    assert error.value.code == code
    assert "SYNTHETIC_PRIVATE" not in repr(error.value) + str(error.value)


@contextmanager
def home_at(path):
    from ara.desktop.data_home import open_home

    home = open_home(path)
    try:
        yield home
    finally:
        assert home.close()


def row(runtime, sql):
    with psycopg.connect(**dict(runtime.connection()), autocommit=True) as conn:
        return conn.execute(sql).fetchall()


def test_first_run_and_reopen_keep_identity_and_committed_data(tmp_path):
    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    with home_at(root) as home:
        runtime = api().ClusterRuntime(home, tools())
        assert runtime.view().phase == "new" and not runtime.view().resources_pending
        assert list(home.path("postgres").iterdir()) == []
        reject("invalid_handle", runtime.connection)
        ready(runtime)
        try:
            identity = runtime.identity()
            assert identity.installation_id == home.identity().installation_id
            assert identity.postgres_major == 18
            assert type(identity.database_oid) is int and identity.database_oid > 0
            assert identity.system_identifier.isascii() and identity.system_identifier.isdigit()
            endpoint = runtime.connection()["host"]
            assert endpoint.startswith("/private/tmp/aira-pg-")
            assert runtime.connection("postgres")["dbname"] == "postgres"
            with psycopg.connect(**dict(runtime.connection()), autocommit=True) as conn:
                conn.execute("CREATE TABLE synthetic_saved_document(value text NOT NULL)")
                conn.execute("INSERT INTO synthetic_saved_document VALUES ('preserve this text')")
            record = (home.path("postgres") / "cluster.json").read_bytes()
            assert json.loads(record) == dict(
                schema_version="aira-pg-cluster/1",
                installation_id=str(identity.installation_id),
                target=tools().target,
                postgres_major=18,
                system_identifier=identity.system_identifier,
                database_name="aira",
                database_oid=identity.database_oid,
            )
            assert not (home.path("postgres") / "initialization.json").exists()
            assert not (home.path("postgres") / "prepared.json").exists()
            assert "SYNTHETIC_PRIVATE" not in repr(runtime) + repr(runtime.view())
        finally:
            closed(runtime)
        assert not Path(endpoint).exists()
        assert home.view().phase == "open"

        reopened = ready(api().ClusterRuntime(home, tools()))
        try:
            assert reopened.identity() == identity
            assert reopened.connection()["host"] != endpoint
            assert row(reopened, "SELECT value FROM synthetic_saved_document") == [
                ("preserve this text",)
            ]
            assert (home.path("postgres") / "cluster.json").read_bytes() == record
        finally:
            closed(reopened)


def test_shutdown_preserves_an_accepted_transaction(tmp_path):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        runtime = ready(api().ClusterRuntime(home, tools()))
        conn = psycopg.connect(**dict(runtime.connection()))
        try:
            conn.execute("CREATE TABLE synthetic_pending_save(value int)")
            conn.execute("INSERT INTO synthetic_pending_save VALUES (42)")
            assert not runtime.shutdown(0.05)
            assert runtime.view().resources_pending
            reject("invalid_handle", runtime.connection)
            conn.commit()
        finally:
            conn.close()
            closed(runtime)
        reopened = ready(api().ClusterRuntime(home, tools()))
        try:
            assert row(reopened, "SELECT value FROM synthetic_pending_save") == [(42,)]
        finally:
            closed(reopened)


def test_new_shutdown_copy_pid_and_immutable_view(tmp_path, monkeypatch):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        runtime = api().ClusterRuntime(home, tools())
        for operation in (
            lambda: copy.copy(runtime),
            lambda: copy.deepcopy(runtime),
            lambda: pickle.dumps(runtime),
        ):
            with pytest.raises(TypeError):
                operation()
        view = runtime.view()
        with pytest.raises(dataclasses.FrozenInstanceError):
            view.phase = "ready"
        original = os.getpid()
        with monkeypatch.context() as change:
            change.setattr(os, "getpid", lambda: original + 1)
            for operation in (
                runtime.start,
                runtime.view,
                runtime.shutdown,
                runtime.connection,
                runtime.identity,
            ):
                reject("invalid_handle", operation)
        assert runtime.shutdown(0)
        reject("invalid_handle", runtime.start)
        assert list(home.path("postgres").iterdir()) == []


@pytest.mark.parametrize("name", ["PGSERVICE", "PGPASSWORD", "PGSERVICEFILE", "PGOPTIONS"])
def test_ambient_libpq_overrides_fail_before_cluster_mutation(tmp_path, monkeypatch, name):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        monkeypatch.setenv(name, "SYNTHETIC_PRIVATE_DO_NOT_READ")
        runtime = api().ClusterRuntime(home, tools())
        runtime.start()
        view = wait(runtime)
        assert view.phase == "failed" and view.error_code == "cluster_unavailable"
        closed(runtime)
        assert list(home.path("postgres").iterdir()) == []


@pytest.mark.parametrize(
    "case", ["foreign", "symlink", "metadata_mode", "duplicate", "missing_record"]
)
def test_ambiguous_or_unsafe_data_are_not_reinitialized(tmp_path, case):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        root = home.path("postgres")
        sentinel = root / "foreign-document"
        if case == "foreign":
            sentinel.write_bytes(b"preserve foreign bytes")
            before = sentinel.read_bytes()
        elif case == "symlink":
            outside = tmp_path / "outside"
            outside.mkdir()
            (root / "data18").symlink_to(outside, target_is_directory=True)
            before = os.readlink(root / "data18")
        elif case == "missing_record":
            (root / "data18").mkdir(mode=0o700)
            sentinel = root / "data18" / "document"
            sentinel.write_bytes(b"preserve data without record")
            before = sentinel.read_bytes()
        else:
            marker = root / "initialization.json"
            raw = json.dumps(
                dict(
                    schema_version="aira-pg-initialization/1",
                    installation_id=str(home.identity().installation_id),
                    target=tools().target,
                )
            ).encode()
            if case == "duplicate":
                raw = raw[:-1] + b',"target":"macos-arm64"}'
            marker.write_bytes(raw)
            marker.chmod(0o644 if case == "metadata_mode" else 0o600)
            before = marker.read_bytes()
        runtime = api().ClusterRuntime(home, tools())
        runtime.start()
        assert wait(runtime).error_code == "cluster_recovery_required"
        closed(runtime)
        assert not (root / "cluster.json").exists()
        if case in ("foreign", "missing_record"):
            assert sentinel.read_bytes() == before
        elif case == "symlink":
            assert os.readlink(root / "data18") == before
        else:
            assert marker.read_bytes() == before


def test_first_only_partial_stage_is_preserved_before_retry(tmp_path):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        root = home.path("postgres")
        marker = root / "initialization.json"
        marker.write_text(
            json.dumps(
                dict(
                    schema_version="aira-pg-initialization/1",
                    installation_id=str(home.identity().installation_id),
                    target=tools().target,
                )
            )
        )
        marker.chmod(0o600)
        stage = root / ".data18.pending"
        stage.mkdir(mode=0o700)
        (stage / "partial-sentinel").write_bytes(b"preserve partial initialization")
        runtime = ready(api().ClusterRuntime(home, tools()))
        try:
            retained = list(root.glob("failed-init-*"))
            assert len(retained) == 1
            assert (
                retained[0] / "partial-sentinel"
            ).read_bytes() == b"preserve partial initialization"
            assert not stage.exists()
        finally:
            closed(runtime)


def test_three_retained_failures_stop_automatic_first_retry(tmp_path):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        root = home.path("postgres")
        marker = root / "initialization.json"
        marker.write_text(
            json.dumps(
                dict(
                    schema_version="aira-pg-initialization/1",
                    installation_id=str(home.identity().installation_id),
                    target=tools().target,
                )
            )
        )
        marker.chmod(0o600)
        stage = root / ".data18.pending"
        stage.mkdir(mode=0o700)
        (stage / "keep").write_bytes(b"keep")
        for _ in range(3):
            (root / ("failed-init-" + str(uuid4()))).mkdir(mode=0o700)
        runtime = api().ClusterRuntime(home, tools())
        runtime.start()
        assert wait(runtime).error_code == "cluster_recovery_required"
        closed(runtime)
        assert (stage / "keep").read_bytes() == b"keep"


def test_missing_application_database_is_not_recreated(tmp_path):
    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        runtime = ready(api().ClusterRuntime(home, tools()))
        record = (home.path("postgres") / "cluster.json").read_bytes()
        database_directories = set((home.path("postgres") / "data18" / "base").iterdir())
        try:
            with psycopg.connect(**dict(runtime.connection("postgres")), autocommit=True) as conn:
                conn.execute("ALTER DATABASE aira RENAME TO synthetic_preserved_database")
        finally:
            closed(runtime)
        reopened = api().ClusterRuntime(home, tools())
        reopened.start()
        assert wait(reopened).error_code == "cluster_recovery_required"
        closed(reopened)
        assert (home.path("postgres") / "cluster.json").read_bytes() == record
        assert set((home.path("postgres") / "data18" / "base").iterdir()) == database_directories


def test_another_runtime_or_live_slot_cannot_mutate_cluster(tmp_path):
    from ara.docx_analysis_worker.macos import acquire_owner

    with home_at(tmp_path.resolve() / "SYNTHETIC_PRIVATE") as home:
        owner = acquire_owner(home.path("postgres"))
        slot = owner.reserve_slot()
        try:
            runtime = api().ClusterRuntime(home, tools())
            runtime.start()
            assert wait(runtime).error_code == "cluster_busy"
            closed(runtime)
            assert not (home.path("postgres") / "initialization.json").exists()
        finally:
            assert owner.release_slot(slot)
            owner.close()
