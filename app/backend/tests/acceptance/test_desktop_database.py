"""Frozen owned database binding; only disposable native clusters and synthetic DOCX."""

import copy
import importlib
import os
import pickle
import sys
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import psycopg
import pytest
from test_desktop_postgres_schema import execute, prepared, world
from test_desktop_postgres_schema import job as schema_job
from test_desktop_postgres_upgrade import payload

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned desktop database")


def api():
    return importlib.import_module("ara.desktop.database")


def reject(code, call):
    with pytest.raises(api().DatabaseError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


@contextmanager
def bound(tmp_path):
    with world(tmp_path) as (home, cluster):
        schema = prepared(home, cluster)
        source = api().bind_database(home, cluster, schema=schema)
        try:
            yield home, cluster, schema, source
        finally:
            assert source.shutdown(5), source.view()


def document(source):
    from ara.docx_documents import import_docx

    runtime = source.document_runtime()
    return import_docx(
        runtime, document_id=uuid4(), title="Synthetic bound document", data=payload()
    )


def test_binding_settings_and_engines_are_inert_and_do_not_load_development_settings(
    tmp_path, monkeypatch
):
    from ara import config
    from ara.docx_analysis_worker.supervisor.database import create_engines

    with world(tmp_path) as (home, cluster):
        schema = prepared(home, cluster)

        def forbidden(*args, **kwargs):
            pytest.fail("Metadata binding opened SQL or loaded development settings")

        with monkeypatch.context() as patch:
            patch.setattr(psycopg, "connect", forbidden)
            patch.setattr(psycopg.Connection, "connect", forbidden)
            patch.setattr(config, "load_settings", forbidden)
            source = api().bind_database(home, cluster, schema=schema)
            try:
                runtime = source.document_runtime()
                settings = source.settings()
                engines = create_engines(replace(settings))
                assert runtime.user_id == home.identity().user_id
                assert runtime.project_id == home.identity().project_id
                assert source.view().phase == "ready"
                assert source.view().connections == source.view().connecting == 0
                assert source.view().resources_pending
                assert "SYNTHETIC_PRIVATE" not in repr(source) + repr(settings)
                with pytest.raises(FrozenInstanceError):
                    source.view().phase = "closed"
                for engine in (
                    runtime.engine,
                    engines.admission,
                    engines.control,
                    engines.publication,
                ):
                    engine.dispose()
            finally:
                assert source.shutdown(0)
        assert source.view().phase == "closed" and not source.view().resources_pending


def test_docx_and_all_supervisor_lanes_use_the_same_owned_database(tmp_path):
    from ara.docx_analysis_worker.supervisor.database import create_engines
    from ara.docx_documents import get_docx

    with bound(tmp_path) as (home, cluster, schema, source):
        before = document(source)
        physical, identity = cluster.identity(), home.identity()
        engines = create_engines(source.settings())
        for engine in (
            source.document_runtime().engine,
            engines.admission,
            engines.control,
            engines.publication,
        ):
            with engine.connect() as connection:
                row = connection.exec_driver_sql(
                    "SELECT (SELECT system_identifier::text FROM pg_control_system()),"
                    "(SELECT oid::bigint FROM pg_database WHERE datname=current_database()),"
                    "current_user,current_setting('search_path'),current_setting('synchronous_commit')"
                ).one()
                assert row == (
                    physical.system_identifier,
                    physical.database_oid,
                    "aira_local",
                    "public,pg_catalog",
                    "on",
                )
                assert connection.exec_driver_sql("SELECT id FROM users").all() == [
                    (identity.user_id,)
                ]
            assert source.view().connections == source.view().connecting == 0
        engines.dispose()
        assert source.shutdown(0)
        reject("invalid_handle", lambda: source.document_runtime().engine.connect())
        again = api().bind_database(home, cluster, schema=schema)
        try:
            assert get_docx(again.document_runtime(), document_id=before.document_id) == before
        finally:
            assert again.shutdown(0)


def test_shutdown_waits_for_accepted_commit_and_rejects_new_connects(tmp_path):
    from ara.docx_documents import get_docx

    with bound(tmp_path) as (home, cluster, schema, source):
        before = document(source)
        runtime = source.document_runtime()
        with runtime.engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql(
                "UPDATE docx_documents SET title='Committed synthetic title' WHERE id=%s",
                (before.document_id,),
            )
            assert not source.shutdown(0.01)
            assert source.view().phase == "stopping" and source.view().connections == 1
            reject("invalid_handle", runtime.engine.connect)
            transaction.commit()
        assert source.shutdown(0)
        assert source.view().phase == "closed" and not source.view().resources_pending
        again = api().bind_database(home, cluster, schema=schema)
        try:
            after = get_docx(again.document_runtime(), document_id=before.document_id)
            assert after.title == "Committed synthetic title"
            assert after.current_data == before.current_data == payload()
        finally:
            assert again.shutdown(0)


def test_environment_rejected_before_native_connection(tmp_path, monkeypatch):
    with bound(tmp_path) as (_, _, _, source):
        runtime = source.document_runtime()
        with monkeypatch.context() as patch:
            patch.setenv("PGSERVICE", "SYNTHETIC_PRIVATE")
            reject("database_unavailable", runtime.engine.connect)
        assert source.view().connections == source.view().connecting == 0
        with runtime.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1


@pytest.mark.parametrize("fault", ["revision", "identity", "replacement"])
def test_actual_sql_binding_rejects_modified_or_replaced_database(tmp_path, fault):
    with bound(tmp_path) as (home, cluster, _, source):
        before = document(source)
        if fault == "revision":
            execute(
                cluster, "UPDATE alembic_version SET version_num='0012_docx_continuous_timeout'"
            )
        elif fault == "identity":
            execute(cluster, "UPDATE docx_analysis_supervisor SET installation_id=%s", (uuid4(),))
        else:
            with psycopg.connect(
                **dict(cluster.connection("postgres")), autocommit=True
            ) as control:
                control.execute("ALTER DATABASE aira RENAME TO retained_synthetic")
                control.execute("CREATE DATABASE aira OWNER aira_local")
        reject("database_mismatch", source.document_runtime().engine.connect)
        assert source.view().connections == source.view().connecting == 0
        kwargs = dict(cluster.connection())
        if fault == "replacement":
            # The closed HBA admits only aira/postgres. Preserve both synthetic
            # databases and restore the original name solely for observation.
            with psycopg.connect(
                **dict(cluster.connection("postgres")), autocommit=True
            ) as control:
                control.execute("ALTER DATABASE aira RENAME TO rejected_synthetic")
                control.execute("ALTER DATABASE retained_synthetic RENAME TO aira")
        with psycopg.connect(**kwargs) as observer:
            actual = observer.execute(
                "SELECT current_data FROM docx_documents WHERE id=%s", (before.document_id,)
            ).fetchone()[0]
            assert bytes(actual) == before.current_data


def test_unprepared_foreign_and_duplicate_handles_cannot_bind(tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    with world(tmp_path) as (home, cluster), world(second) as (other_home, other_cluster):
        reject(
            "invalid_handle",
            lambda: api().bind_database(home, cluster, schema=schema_job(home, cluster)),
        )
        schema = prepared(home, cluster)
        other_schema = prepared(other_home, other_cluster)
        reject(
            "validation_error", lambda: api().bind_database(home, cluster, schema=schema.receipt())
        )
        reject("invalid_handle", lambda: api().bind_database(home, cluster, schema=other_schema))
        source = api().bind_database(home, cluster, schema=schema)
        try:
            reject("database_busy", lambda: api().bind_database(home, cluster, schema=schema))
        finally:
            assert source.shutdown(0)


def test_process_local_source_and_timeout_validation(tmp_path, monkeypatch):
    with bound(tmp_path) as (_, _, _, source):
        for fn in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                fn(source)
        for value in (True, -1, 6, 10**1000, float("inf"), float("nan")):
            reject("validation_error", lambda: source.shutdown(value))
            assert source.view().phase == "ready"
        pid = os.getpid()
        with monkeypatch.context() as patch:
            patch.setattr(os, "getpid", lambda: pid + 1)
            for fn in (source.view, source.settings, source.document_runtime, source.shutdown):
                reject("invalid_handle", fn)


def test_native_connection_caps_are_per_lane_and_release_on_checkin(tmp_path):
    from ara.docx_analysis_worker.supervisor.database import create_engines

    with bound(tmp_path) as (_, _, _, source):
        engine = source.document_runtime().engine
        connections = [engine.connect() for _ in range(4)]
        engines = create_engines(source.settings())
        try:
            reject("database_busy", engine.connect)
            with (
                engines.control.connect(),
                engines.admission.connect(),
                engines.publication.connect(),
            ):
                reject("database_busy", engines.control.connect)
                assert source.view().connections == 7
        finally:
            for connection in connections:
                connection.close()
            engines.dispose()
        assert source.view().connections == source.view().connecting == 0
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
