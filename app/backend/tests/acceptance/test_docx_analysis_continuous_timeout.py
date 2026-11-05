"""F3 additive timeout schema: truthful timestamps and lossless history gates."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_docx_analysis_runs_start import world as world
from test_docx_analysis_storage_migrations import (
    migrate_down,
    parents,
    put,
    records,
)
from test_docx_analysis_supervisor_runtime import finished, submit, wait_for
from test_docx_analysis_supervisor_runtime import rig as rig
from test_docx_storage_transactions import bounded_connections, observe_backend, wait_for_lock
from test_migrations import _schema_signature

from ara.config import DatabaseSettings
from ara.docx_analysis_worker.supervisor import database
from ara.docx_analysis_worker.supervisor.sql_models import SupervisorStorageError

V11, V12 = "0011_docx_analysis_supervisor", "0012_docx_continuous_timeout"
TABLE = "docx_analysis_runs"


@pytest.fixture
def pg_engine(empty_pg_engine, apply_migrations):
    """Pin historical timeout acceptance to its own V12 schema."""
    apply_migrations(empty_pg_engine, V12)
    return empty_pg_engine


def snapshot(conn):
    return {
        name: conn.execute(text(f'SELECT * FROM "{name}"')).all()
        for name in sorted(set(inspect(conn).get_table_names()) - {"alembic_version"})
    }


def seed(engine, status="timed_out", *, continuous=False, early=True):
    with engine.begin() as conn:
        rows = records(parents(conn), status)
        if continuous:
            rows[0]["timeout_basis"] = "continuous"
            if early:
                rows[0]["finished_at"] = rows[0]["created_at"] + timedelta(seconds=1)
        put(conn, rows)
    return rows[0]


def test_upgrade_preserves_all_history_and_repeat(empty_pg_engine, apply_migrations):
    engine = empty_pg_engine
    apply_migrations(engine, V11)
    for status in (
        "queued",
        "running",
        "cancel_requested",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
    ):
        seed(engine, status)
    with engine.connect() as conn:
        before = snapshot(conn)
        columns = [c["name"] for c in inspect(conn).get_columns(TABLE)]
    apply_migrations(engine, V12)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V12
        after = snapshot(conn)
        after[TABLE] = conn.execute(text("SELECT " + ",".join(columns) + " FROM " + TABLE)).all()
        assert after == before
        assert conn.execute(text("SELECT DISTINCT timeout_basis FROM " + TABLE)).all() == [
            ("wall",)
        ]
        signature = _schema_signature(conn)
    apply_migrations(engine, V12)
    with engine.connect() as conn:
        assert _schema_signature(conn) == signature


def test_wall_only_downgrade_restores_exact_v11(empty_pg_engine, apply_migrations):
    engine = empty_pg_engine
    apply_migrations(engine, V11)
    seed(engine)
    with engine.connect() as conn:
        signature, before = _schema_signature(conn), snapshot(conn)
    apply_migrations(engine, V12)
    migrate_down(engine, V11)
    with engine.connect() as conn:
        assert _schema_signature(conn) == signature
        assert snapshot(conn) == before
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V11


@pytest.mark.parametrize("early", [False, True])
def test_continuous_history_cannot_be_downgraded(pg_engine, early):
    seed(pg_engine, continuous=True, early=early)
    with pg_engine.connect() as conn:
        before, signature = snapshot(conn), _schema_signature(conn)
    with pytest.raises(RuntimeError, match="continuous timeout history"):
        migrate_down(pg_engine, V11)
    with pg_engine.connect() as conn:
        assert snapshot(conn) == before
        assert _schema_signature(conn) == signature
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V12


@pytest.mark.parametrize("value", [None, "", "unknown", "WALL"])
def test_invalid_basis_rejected_at_commit(pg_engine, value):
    row = seed(pg_engine, "queued")
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text("UPDATE " + TABLE + " SET timeout_basis=:v"), {"v": value})
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT id,status,timeout_basis FROM " + TABLE)).one() == (
            row["id"],
            "queued",
            "wall",
        )


@pytest.mark.parametrize(
    "status", ["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled"]
)
def test_continuous_is_exclusive_to_timeout(pg_engine, status):
    seed(pg_engine, status)
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text("UPDATE " + TABLE + " SET timeout_basis='continuous'"))


def test_wall_still_rejects_early_timeout_and_bad_reason(pg_engine):
    seed(pg_engine)
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text("UPDATE " + TABLE + " SET finished_at=created_at"))
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE " + TABLE + " SET timeout_basis='continuous',error_code='cancelled'")
        )


@pytest.mark.parametrize("commit", [False, True])
def test_downgrade_waits_for_writer_then_rechecks(pg_engine, commit):
    row = seed(pg_engine)
    with bounded_connections(pg_engine), ThreadPoolExecutor(max_workers=1) as pool:
        with pg_engine.connect() as writer:
            tx = writer.begin()
            writer.execute(
                text("UPDATE " + TABLE + " SET timeout_basis='continuous' WHERE id=:id"),
                {"id": row["id"]},
            )
            with observe_backend(pg_engine) as (started, backend):
                future = pool.submit(migrate_down, pg_engine, V11)
                wait_for_lock(pg_engine, started, backend)
                assert not future.done()
                tx.commit() if commit else tx.rollback()
                if commit:
                    with pytest.raises(RuntimeError, match="continuous timeout history"):
                        future.result(timeout=5)
                else:
                    future.result(timeout=5)
    with pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
            V12 if commit else V11
        )
        assert conn.scalar(text("SELECT count(*) FROM " + TABLE)) == 1
        if commit:
            assert conn.scalar(text("SELECT timeout_basis FROM " + TABLE)) == "continuous"


@pytest.mark.parametrize("revision", ["0010_docx_analysis_storage", V11, V12, "0099_future"])
def test_startup_accepts_only_current_version(empty_pg_engine, apply_migrations, revision):
    engine = empty_pg_engine
    apply_migrations(engine, revision if revision != "0099_future" else V12)
    if revision == "0099_future":
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num='0099_future'"))
    engines = database.create_engines(
        DatabaseSettings(engine.url.render_as_string(hide_password=False))
    )
    try:
        if revision == V12:
            database.check_database(engines.control)
        else:
            with pytest.raises(SupervisorStorageError) as error:
                database.check_database(engines.control)
            assert error.value.code == "recovery_required"
    finally:
        engines.dispose()


def test_local_timeout_is_truthful_and_replay_preserves_basis(rig, world):
    s, p = rig
    p.done.clear()
    ticket = submit(s, world)
    wait_for(p.entered.is_set)
    p.clock.advance(301_000_000_000)
    wait_for(p.stopped.is_set)
    p.done.set()
    out = finished(s, ticket)
    assert out.sql_state.summary.status == "timed_out"
    with world["engine"].connect() as conn:
        stored = conn.execute(
            text("SELECT created_at,deadline_at,finished_at,timeout_basis FROM " + TABLE)
        ).one()
    assert stored.created_at <= stored.finished_at < stored.deadline_at
    assert stored.timeout_basis == "continuous"
    assert (stored.deadline_at - stored.created_at).total_seconds() == 300
    s.stop(ticket)
    assert finished(s, ticket).sql_state == out.sql_state
    with world["engine"].connect() as conn:
        assert (
            conn.execute(
                text("SELECT created_at,deadline_at,finished_at,timeout_basis FROM " + TABLE)
            ).one()
            == stored
        )
