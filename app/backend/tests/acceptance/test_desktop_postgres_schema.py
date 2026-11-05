"""First schema ownership and restart acceptance, on disposable native PG only."""

import copy
import dataclasses
import importlib
import json
import os
import pickle
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from test_desktop_postgres_cluster import closed, home_at, ready, tools

V13 = "0013_docx_review_preferences"
V8 = "0008_docx_edit_drafts"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned schema")


def api():
    return importlib.import_module("ara.desktop.postgres_schema")


@contextmanager
def world(path):
    from ara.desktop.postgres_cluster import ClusterRuntime

    with home_at(path.resolve() / "SYNTHETIC_PRIVATE") as home:
        cluster = ready(ClusterRuntime(home, tools()))
        try:
            yield home, cluster
        finally:
            closed(cluster)


def job(home, cluster, **kwargs):
    return api().SchemaPreparation(
        home, cluster, migrations=kwargs.pop("migrations", Path.cwd() / "migrations"), **kwargs
    )


def settled(preparation):
    end = time.monotonic() + 20
    while time.monotonic() < end:
        view = preparation.view()
        if view.phase in ("ready", "failed", "closed") and not view.resources_pending:
            return view
        time.sleep(0.01)
    pytest.fail("Synthetic schema preparation did not settle")


def prepared(home, cluster):
    operation = job(home, cluster)
    operation.start()
    assert settled(operation).phase == "ready", operation.view()
    return operation


def reject(code, operation):
    with pytest.raises(api().SchemaError) as caught:
        operation()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


@contextmanager
def engine_for(cluster):
    engine = create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(**dict(cluster.connection())),
        poolclass=NullPool,
        hide_parameters=True,
    )
    try:
        yield engine
    finally:
        engine.dispose()


def execute(cluster, query, params=None):
    with psycopg.connect(**dict(cluster.connection()), autocommit=True) as connection:
        cursor = connection.execute(query, params)
        return cursor.fetchall() if cursor.description else None


def relations(cluster):
    return execute(
        cluster,
        "SELECT relname,relkind FROM pg_class c JOIN pg_namespace n "
        "ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY relname",
    )


def test_first_run_seeds_stable_identity_and_reopens_exact_docx(tmp_path, monkeypatch):
    from ara import config
    from ara.documents.runtime import DocumentRuntime
    from ara.docx_documents import get_docx, import_docx
    from ara.docx_package.creation import NewParagraph, create_docx

    def forbidden(*args, **kwargs):
        raise AssertionError("Must not load secrets/settings")

    monkeypatch.setattr(config, "load_settings", forbidden)
    with world(tmp_path) as (home, cluster):
        operation = prepared(home, cluster)
        receipt = operation.receipt()
        identity = home.identity()
        assert (receipt.installation_id, receipt.user_id, receipt.project_id) == (
            identity.installation_id,
            identity.user_id,
            identity.project_id,
        )
        assert receipt.revision == V13
        assert receipt.system_identifier == cluster.identity().system_identifier
        assert receipt.database_oid == cluster.identity().database_oid
        assert execute(cluster, "SELECT id FROM users") == [(identity.user_id,)]
        assert execute(cluster, "SELECT id,owner_id,name FROM projects") == [
            (identity.project_id, identity.user_id, "AIRA")
        ]
        assert execute(
            cluster, "SELECT phase,revision,installation_id FROM docx_analysis_supervisor"
        ) == [("clean", 2, identity.installation_id)]
        document_id = uuid4()
        payload = create_docx((NewParagraph("Preserve this synthetic requirement"),))
        with engine_for(cluster) as engine:
            runtime = DocumentRuntime(
                engine=engine,
                user_id=identity.user_id,
                project_id=identity.project_id,
                mode="local",
            )
            before = import_docx(runtime, document_id=document_id, title="Synthetic", data=payload)
        journal = home.path("backups") / "schema"
        raw = (journal / "ready.json").read_bytes()
        assert not (journal / "initializing.json").exists()
        assert json.loads(raw) == dict(
            schema_version="aira-schema-ready/1",
            installation_id=str(receipt.installation_id),
            user_id=str(receipt.user_id),
            project_id=str(receipt.project_id),
            system_identifier=receipt.system_identifier,
            database_oid=receipt.database_oid,
            revision=V13,
        )
        assert operation.shutdown(0)
        assert operation.receipt() == receipt
        reopened = prepared(home, cluster)
        assert reopened.receipt() == receipt
        assert (journal / "ready.json").read_bytes() == raw
        with engine_for(cluster) as engine:
            runtime = DocumentRuntime(
                engine=engine,
                user_id=identity.user_id,
                project_id=identity.project_id,
                mode="local",
            )
            assert get_docx(runtime, document_id=document_id) == before


def test_inert_handle_pid_copy_and_new_shutdown(tmp_path, monkeypatch):
    with world(tmp_path) as (home, cluster):
        operation = job(home, cluster)
        assert operation.view().phase == "new" and not operation.view().resources_pending
        assert list(home.path("backups").iterdir()) == []
        reject("invalid_handle", operation.receipt)
        for call in (
            lambda: copy.copy(operation),
            lambda: copy.deepcopy(operation),
            lambda: pickle.dumps(operation),
        ):
            with pytest.raises(TypeError):
                call()
        view = operation.view()
        with pytest.raises(dataclasses.FrozenInstanceError):
            view.phase = "ready"
        pid = os.getpid()
        with monkeypatch.context() as patch:
            patch.setattr(os, "getpid", lambda: pid + 1)
            for call in (operation.start, operation.view, operation.shutdown, operation.receipt):
                reject("invalid_handle", call)
        assert operation.shutdown(0)
        reject("invalid_handle", operation.start)
        assert list(home.path("backups").iterdir()) == []
        assert relations(cluster) == []


@pytest.mark.parametrize(
    "case",
    [
        "missing_record",
        "corrupt_record",
        "foreign_record",
        "missing_schema",
        "missing_column",
        "foreign_user",
        "view",
    ],
)
def test_damaged_completed_schema_is_never_reseeded(tmp_path, case):
    with world(tmp_path) as (home, cluster):
        prepared(home, cluster)
        path = home.path("backups") / "schema" / "ready.json"
        if case == "missing_record":
            path.unlink()
        elif case == "corrupt_record":
            path.write_bytes(b'{"incomplete":')
        elif case == "foreign_record":
            value = json.loads(path.read_bytes())
            value["user_id"] = str(uuid4())
            path.write_text(json.dumps(value))
        elif case == "missing_schema":
            execute(cluster, "DROP SCHEMA public CASCADE")
            execute(cluster, "CREATE SCHEMA public")
        elif case == "missing_column":
            execute(cluster, "ALTER TABLE docx_documents DROP COLUMN title")
        elif case == "foreign_user":
            execute(cluster, "INSERT INTO users(id) VALUES (%s)", (uuid4(),))
        elif case == "view":
            execute(cluster, "CREATE VIEW synthetic_foreign_view AS SELECT 42 AS sentinel")
        before_relations = relations(cluster)
        before_record = path.read_bytes() if path.exists() else None
        operation = job(home, cluster)
        operation.start()
        assert settled(operation).error_code == "schema_recovery_required"
        assert relations(cluster) == before_relations
        assert (path.read_bytes() if path.exists() else None) == before_record
        assert not (path.parent / "initializing.json").exists()


def test_old_schema_is_preserved_for_explicit_backup_upgrade(tmp_path):
    with world(tmp_path) as (home, cluster):
        with engine_for(cluster) as engine, engine.begin() as connection:
            cfg = Config()
            cfg.set_main_option("script_location", str(Path.cwd() / "migrations"))
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, V8)
        before = relations(cluster)
        operation = job(home, cluster)
        operation.start()
        assert settled(operation).error_code == "schema_upgrade_required"
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V8,)]
        assert relations(cluster) == before
        assert not (home.path("backups") / "schema" / "initializing.json").exists()


def test_nonempty_unknown_database_is_not_adopted(tmp_path):
    with world(tmp_path) as (home, cluster):
        execute(cluster, "CREATE TABLE synthetic_document(value text)")
        execute(cluster, "INSERT INTO synthetic_document VALUES ('preserve')")
        operation = job(home, cluster)
        operation.start()
        assert settled(operation).error_code == "schema_recovery_required"
        assert execute(cluster, "SELECT value FROM synthetic_document") == [("preserve",)]
        assert execute(cluster, "SELECT to_regclass('public.alembic_version')") == [(None,)]


def test_existing_analysis_fence_is_not_reset(tmp_path):
    with world(tmp_path) as (home, cluster):
        prepared(home, cluster)
        values = tuple(uuid4() for _ in range(6))
        execute(
            cluster,
            "UPDATE docx_analysis_supervisor SET phase='armed',revision=5,"
            "owner_epoch=%s,launch_id=%s,document_id=%s,run_id=%s,attempt_id=%s,"
            "worker_instance_id=%s,claim_fence=1",
            values,
        )
        before = execute(cluster, "SELECT * FROM docx_analysis_supervisor")
        prepared(home, cluster)
        assert execute(cluster, "SELECT * FROM docx_analysis_supervisor") == before


@pytest.mark.parametrize("entry", ["foreign", "link", "mode"])
def test_unsafe_journal_preserves_all_files(tmp_path, entry):
    with world(tmp_path) as (home, cluster):
        journal = home.path("backups") / "schema"
        journal.mkdir(mode=0o700)
        if entry == "foreign":
            (journal / "foreign").write_bytes(b"preserve")
        elif entry == "link":
            target = tmp_path / "outside"
            target.write_bytes(b"preserve")
            (journal / "ready.json").symlink_to(target)
        else:
            (journal / "initializing.json").write_bytes(b"preserve")
            (journal / "initializing.json").chmod(0o644)
        operation = job(home, cluster)
        operation.start()
        assert settled(operation).error_code == "schema_recovery_required"
        assert relations(cluster) == []
        assert not (journal / ".ready.json.pending").exists()
