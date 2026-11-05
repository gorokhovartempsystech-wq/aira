"""E2A additive review preference schema and lossless migration boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_docx_analysis_storage_migrations import H, insert, migrate_down, parents, put, records
from test_docx_storage_transactions import bounded_connections, observe_backend, wait_for_lock
from test_migrations import _schema_signature

from ara.config import DatabaseSettings
from ara.docx_analysis_worker.supervisor import database
from ara.docx_analysis_worker.supervisor.sql_models import SupervisorStorageError

V12, V13 = "0012_docx_continuous_timeout", "0013_docx_review_preferences"
P, D, R = "docx_review_preferences", "docx_review_dismissals", "docx_review_receipts"
TABLES = {P, D, R}


def old_state(conn):
    signature = json.loads(_schema_signature(conn))
    for table in TABLES | {"alembic_version"}:
        signature.pop(table, None)
    return signature, {
        table: conn.execute(text(f'SELECT * FROM "{table}"')).all() for table in sorted(signature)
    }


def seed(conn):
    scope = parents(conn)
    rows = records(scope, "succeeded")
    put(conn, rows)
    return scope[0], rows[0]["id"]


def preference(document_id, **changes):
    return dict(document_id=document_id, revision=1) | changes


def dismissal(document_id, run_id, **changes):
    return (
        dict(
            document_id=document_id,
            dismissal_key="dh-" + H,
            source_run_id=run_id,
            source_result_sha256=H,
            source_finding_id="df-" + H,
            hidden_at_revision=1,
        )
        | changes
    )


def receipt(document_id, **changes):
    return (
        dict(
            document_id=document_id,
            command_id=uuid4(),
            expected_revision=0,
            revision=1,
            kind="preferences",
            command_data=b"{}",
            command_sha256=H,
            response_data=b"{}",
            response_sha256=H,
        )
        | changes
    )


@pytest.fixture
def review_schema(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine, V13)
    with empty_pg_engine.begin() as conn:
        document_id, run_id = seed(conn)
    return empty_pg_engine, document_id, run_id


def test_upgrade_preserves_every_old_table_and_matches_orm(empty_pg_engine, apply_migrations):
    from ara.db import Base
    from ara.models import DocxReviewDismissal, DocxReviewPreferences, DocxReviewReceipt

    assert {
        c.__tablename__ for c in (DocxReviewDismissal, DocxReviewPreferences, DocxReviewReceipt)
    } == TABLES
    engine = empty_pg_engine
    apply_migrations(engine, V12)
    with engine.begin() as conn:
        for status in (
            "queued",
            "running",
            "cancel_requested",
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
        ):
            put(conn, records(parents(conn), status))
        before = old_state(conn)
    apply_migrations(engine, V13)
    with engine.connect() as conn:
        assert old_state(conn) == before
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V13
        assert set(inspect(conn).get_table_names()) - set(before[0]) - {"alembic_version"} == TABLES
        for table in TABLES:
            assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        assert (
            compare_metadata(
                MigrationContext.configure(
                    conn, opts={"compare_type": True, "compare_server_default": True}
                ),
                Base.metadata,
            )
            == []
        )
        signature = _schema_signature(conn)
    apply_migrations(engine, V13)
    with engine.connect() as conn:
        assert old_state(conn) == before and _schema_signature(conn) == signature
    migrate_down(engine, V12)
    with engine.connect() as conn:
        assert old_state(conn) == before
        assert not TABLES.intersection(inspect(conn).get_table_names())


def test_defaults_keys_and_small_receipt(review_schema):
    engine, doc, run = review_schema
    with engine.begin() as conn:
        insert(conn, P, preference(doc))
        insert(conn, D, dismissal(doc, run))
        insert(conn, R, receipt(doc))
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT revision,disabled_types,show_questions,show_hidden,created_at,updated_at "
                f"FROM {P}"
            )
        ).one()
        assert row[:4] == (1, [], True, False) and row.updated_at >= row.created_at
        assert conn.scalar(text(f"SELECT count(*) FROM {D}")) == 1
        assert conn.scalar(text(f"SELECT octet_length(response_data) FROM {R}")) == 2
        expected = {
            P: {
                "document_id",
                "revision",
                "disabled_types",
                "show_questions",
                "show_hidden",
                "created_at",
                "updated_at",
            },
            D: {
                "document_id",
                "dismissal_key",
                "source_run_id",
                "source_result_sha256",
                "source_finding_id",
                "hidden_at_revision",
                "created_at",
            },
            R: {
                "document_id",
                "command_id",
                "expected_revision",
                "revision",
                "kind",
                "command_data",
                "command_sha256",
                "response_data",
                "response_sha256",
                "created_at",
            },
        }
        for table in TABLES:
            columns = inspect(conn).get_columns(table)
            assert {c["name"] for c in columns} == expected[table]
            assert all(c["nullable"] is False for c in columns)


@pytest.mark.parametrize(
    "value",
    [
        "null",
        "{}",
        '["unknown"]',
        '["formulation","formulation"]',
        '["formulation","duplicate"]',
        "[1]",
        '[["duplicate"]]',
    ],
)
def test_filter_json_requires_unique_canonical_known_types(review_schema, value):
    engine, doc, _ = review_schema
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {P}(document_id,revision,disabled_types) "
                "VALUES (:doc,1,CAST(:value AS jsonb))"
            ),
            dict(doc=doc, value=value),
        )
    with engine.connect() as conn:
        assert conn.scalar(text(f"SELECT count(*) FROM {P}")) == 0


@pytest.mark.parametrize(
    "table,changes",
    [
        (P, {"revision": 0}),
        (P, {"show_questions": None}),
        (P, {"created_at": "infinity"}),
        (D, {"dismissal_key": "dh-" + "G" * 64}),
        (D, {"source_finding_id": "df-short"}),
        (D, {"hidden_at_revision": 0}),
        (D, {"source_result_sha256": "b" * 64}),
        (R, {"expected_revision": -1}),
        (R, {"revision": 3}),
        (R, {"kind": "apply"}),
        (R, {"command_data": b""}),
        (R, {"command_data": b"x" * 16385}),
        (R, {"response_data": b"x" * 2049}),
        (R, {"response_sha256": "private"}),
    ],
)
def test_commit_constraints_reject_bad_metadata(review_schema, table, changes):
    engine, doc, run = review_schema
    if table != P:
        with engine.begin() as conn:
            insert(conn, P, preference(doc))
    row = preference(doc) if table == P else dismissal(doc, run) if table == D else receipt(doc)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        insert(conn, table, row | changes)
    with engine.connect() as conn:
        assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0


def test_dismissal_cannot_reference_another_document_result(review_schema):
    engine, doc, run = review_schema
    with engine.begin() as conn:
        other, _ = seed(conn)
        insert(conn, P, preference(other))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        insert(conn, D, dismissal(other, run))
    with engine.connect() as conn:
        assert conn.scalar(text(f"SELECT count(*) FROM {D}")) == 0


def test_receipts_have_unique_document_revision_and_command(review_schema):
    engine, doc, _ = review_schema
    row = receipt(doc)
    with engine.begin() as conn:
        insert(conn, P, preference(doc))
        insert(conn, R, row)
    for changes in ({"command_id": uuid4()}, {"expected_revision": 1, "revision": 2}):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            insert(conn, R, row | changes)
    with engine.connect() as conn:
        assert conn.scalar(text(f"SELECT count(*) FROM {R}")) == 1


def test_nonempty_downgrade_keeps_all_data_and_schema(review_schema):
    engine, doc, run = review_schema
    with engine.begin() as conn:
        insert(conn, P, preference(doc))
        insert(conn, D, dismissal(doc, run))
        insert(conn, R, receipt(doc))
        signature = _schema_signature(conn)
        before = {t: conn.execute(text(f"SELECT * FROM {t}")).all() for t in TABLES}
    with pytest.raises(RuntimeError, match="Cannot downgrade DOCX review preferences"):
        migrate_down(engine, V12)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V13
        assert _schema_signature(conn) == signature
        assert {t: conn.execute(text(f"SELECT * FROM {t}")).all() for t in TABLES} == before


@pytest.mark.parametrize("commit", [True, False])
def test_downgrade_waits_for_writer_before_empty_check(review_schema, commit):
    engine, doc, _ = review_schema
    with bounded_connections(engine), ThreadPoolExecutor(max_workers=1) as pool:
        with engine.connect() as writer:
            tx = writer.begin()
            insert(writer, P, preference(doc))
            with observe_backend(engine) as (started, backend):
                future = pool.submit(migrate_down, engine, V12)
                wait_for_lock(engine, started, backend)
                assert not future.done()
                tx.commit() if commit else tx.rollback()
                if commit:
                    with pytest.raises(
                        RuntimeError, match="Cannot downgrade DOCX review preferences"
                    ):
                        future.result(timeout=5)
                else:
                    future.result(timeout=5)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
            V13 if commit else V12
        )
        if commit:
            assert conn.scalar(text(f"SELECT count(*) FROM {P}")) == 1


@pytest.mark.parametrize(
    "revision,accepted",
    [
        (V12, True),
        (V13, True),
        ("0011_docx_analysis_supervisor", False),
        ("0010_docx_analysis_storage", False),
        ("0099_future", False),
    ],
)
def test_supervisor_accepts_exact_supported_versions(
    empty_pg_engine, apply_migrations, revision, accepted
):
    engine = empty_pg_engine
    apply_migrations(engine, V13 if revision == "0099_future" else revision)
    if revision == "0099_future":
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num='0099_future'"))
    engines = database.create_engines(
        DatabaseSettings(engine.url.render_as_string(hide_password=False))
    )
    try:
        if accepted:
            database.check_database(engines.control)
        else:
            with pytest.raises(SupervisorStorageError) as caught:
                database.check_database(engines.control)
            assert caught.value.code == "recovery_required"
    finally:
        engines.dispose()


def test_failed_older_downgrade_rolls_back_removal_of_empty_review_tables(review_schema):
    from datetime import timedelta

    engine, _, _ = review_schema
    with engine.begin() as conn:
        rows = records(parents(conn), "timed_out")
        rows[0]["timeout_basis"] = "continuous"
        rows[0]["finished_at"] = rows[0]["created_at"] + timedelta(seconds=1)
        put(conn, rows)
        signature, before = _schema_signature(conn), old_state(conn)
    with pytest.raises(RuntimeError, match="continuous timeout history"):
        migrate_down(engine, "0011_docx_analysis_supervisor")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V13
        assert _schema_signature(conn) == signature and old_state(conn) == before
        assert TABLES.issubset(inspect(conn).get_table_names())
