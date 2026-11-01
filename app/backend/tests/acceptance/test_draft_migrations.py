"""Independent D01-01 schema acceptance; synthetic disposable PostgreSQL only."""

from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import BigInteger, Text, inspect, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from test_analysis_run_migrations import ROOT, _seed_history
from test_review_migrations import _review
from test_worker_migrations import _attempt, _seed_run

V4 = "0004_review_revisions"
V5 = "0005_document_drafts"
OLD_TABLES = (
    "users",
    "projects",
    "documents",
    "document_versions",
    "context_revisions",
    "analysis_runs",
    "analysis_attempts",
    "review_revisions",
)
MARKDOWN = "  # Черновик\r\n\r\n- Точное имя\r\n```unfinished\r\n  текст  "


def _snapshot(connection):
    inspector = inspect(connection)
    return {
        table: {
            "rows": connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all(),
            "columns": [
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns(table)
            ],
            "pk": inspector.get_pk_constraint(table),
            "foreign_keys": inspector.get_foreign_keys(table),
            "unique": inspector.get_unique_constraints(table),
            "checks": inspector.get_check_constraints(table),
            "indexes": inspector.get_indexes(table),
        }
        for table in OLD_TABLES
    }


def _seed_complete_history(connection):
    ids, run_id = _seed_run(connection)
    attempt_id = _attempt(connection, ids, run_id)
    connection.execute(
        text(
            "UPDATE analysis_attempts SET status='succeeded', finished_at=clock_timestamp() "
            "WHERE id=:id"
        ),
        {"id": attempt_id},
    )
    connection.execute(
        text(
            "UPDATE analysis_runs SET status='succeeded', attempt_count=1, max_attempts=3, "
            "deadline_at=clock_timestamp()+interval '1 minute', completed_at=clock_timestamp(), "
            "incomplete_review=false, result_payload='{}'::jsonb WHERE id=:id"
        ),
        {"id": run_id},
    )
    first = _review(connection, run_id, ids["owners"][0])
    _review(connection, run_id, ids["owners"][0], parent=first, number=2)
    return ids


def _draft(connection, ids, **overrides):
    row = {
        "document_id": ids["documents"][0],
        "base_version_id": ids["versions"][0],
        "revision": 1,
        "content_markdown": MARKDOWN,
        **overrides,
    }
    connection.execute(
        text(
            "INSERT INTO document_drafts "
            "(document_id, base_version_id, revision, content_markdown) "
            "VALUES (:document_id, :base_version_id, :revision, :content_markdown)"
        ),
        row,
    )


def test_draft_upgrade_repeat_downgrade_preserves_all_eight_old_tables(
    empty_pg_engine, apply_migrations
):
    apply_migrations(empty_pg_engine, V4)
    with empty_pg_engine.begin() as connection:
        ids = _seed_complete_history(connection)
        before = _snapshot(connection)
        assert all(state["rows"] for state in before.values())
    apply_migrations(empty_pg_engine, V5)
    with empty_pg_engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V5
        assert _snapshot(connection) == before
        assert set(inspect(connection).get_table_names()) == {
            *OLD_TABLES,
            "document_drafts",
            "alembic_version",
        }
        _draft(connection, ids)
        draft = connection.execute(text("SELECT * FROM document_drafts")).one()
    apply_migrations(empty_pg_engine, V5)
    with empty_pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V5
        assert _snapshot(connection) == before
        assert connection.execute(text("SELECT * FROM document_drafts")).one() == draft

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_pg_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, V4)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V4
        assert _snapshot(connection) == before
        assert set(inspect(connection).get_table_names()) == {*OLD_TABLES, "alembic_version"}
    apply_migrations(empty_pg_engine, V5)
    with empty_pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V5
        assert _snapshot(connection) == before
        assert connection.scalar(text("SELECT count(*) FROM document_drafts")) == 0


def test_draft_model_exact_columns_types_defaults_and_named_constraints(pg_engine):
    from ara.db import Base
    from ara.models import DocumentDraft

    assert DocumentDraft.__tablename__ == "document_drafts"
    assert DocumentDraft.__table__ is Base.metadata.tables["document_drafts"]
    inspector = inspect(pg_engine)
    columns = {column["name"]: column for column in inspector.get_columns("document_drafts")}
    assert set(columns) == {
        "document_id",
        "base_version_id",
        "revision",
        "content_markdown",
        "updated_at",
    }
    assert all(not column["nullable"] for column in columns.values())
    assert inspector.get_pk_constraint("document_drafts")["constrained_columns"] == ["document_id"]
    assert isinstance(columns["document_id"]["type"], UUID)
    assert isinstance(columns["base_version_id"]["type"], UUID)
    assert isinstance(columns["revision"]["type"], BigInteger)
    assert columns["revision"]["default"] is None
    assert isinstance(columns["content_markdown"]["type"], Text)
    assert columns["updated_at"]["type"].timezone is True
    assert columns["updated_at"]["default"] == "clock_timestamp()"
    foreign_keys = inspector.get_foreign_keys("document_drafts")
    assert {
        (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
        )
        for item in foreign_keys
    } == {
        (("document_id",), "documents", ("id",)),
        (("document_id", "base_version_id"), "document_versions", ("document_id", "id")),
    }
    assert all(item["name"] for item in foreign_keys)
    assert all(
        item["options"].get("ondelete", "NO ACTION") in {"NO ACTION", "RESTRICT"}
        for item in foreign_keys
    )
    checks = inspector.get_check_constraints("document_drafts")
    assert any(item["name"] and "revision" in item["sqltext"] for item in checks)


@pytest.mark.parametrize(
    "overrides",
    [
        {"revision": 0},
        {"revision": -1},
        {"revision": None},
        {"document_id": None},
        {"base_version_id": None},
        {"content_markdown": None},
        {"document_id": uuid4()},
        {"base_version_id": uuid4()},
    ],
)
def test_draft_database_rejects_invalid_revision_nulls_and_missing_foreign_keys(
    pg_engine, overrides
):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _draft(connection, ids, **overrides)
        assert connection.scalar(text("SELECT count(*) FROM document_drafts")) == 0


def test_draft_requires_explicit_revision_and_nonnull_timestamp(pg_engine):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO document_drafts (document_id, base_version_id, content_markdown) "
                    "VALUES (:document, :version, '')"
                ),
                {"document": ids["documents"][0], "version": ids["versions"][0]},
            )
        _draft(connection, ids)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("UPDATE document_drafts SET updated_at=NULL"))


def test_draft_accepts_empty_text_and_bigint_range_with_database_timestamp(pg_engine):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        before = connection.scalar(text("SELECT clock_timestamp()"))
        _draft(connection, ids, content_markdown="", revision=2**31 + 1)
        after = connection.scalar(text("SELECT clock_timestamp()"))
        draft = connection.execute(text("SELECT * FROM document_drafts")).mappings().one()
        assert draft["revision"] == 2**31 + 1
        assert draft["content_markdown"] == ""
        assert before <= draft["updated_at"] <= after
        assert draft["updated_at"].utcoffset() is not None
        connection.execute(
            text("UPDATE document_drafts SET revision=:revision, content_markdown=:content"),
            {"revision": 2**63 - 1, "content": MARKDOWN},
        )
    with pg_engine.connect() as connection:
        assert connection.execute(
            text("SELECT revision, content_markdown FROM document_drafts")
        ).one() == (2**63 - 1, MARKDOWN)


def test_draft_is_unique_per_document_and_base_cannot_cross_documents(pg_engine):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        with pytest.raises(IntegrityError) as wrong_base, connection.begin_nested():
            _draft(connection, ids, base_version_id=ids["versions"][1])
        assert wrong_base.value.orig.sqlstate == "23503"
        _draft(connection, ids)
        with pytest.raises(IntegrityError) as duplicate, connection.begin_nested():
            _draft(connection, ids, revision=2)
        assert duplicate.value.orig.sqlstate == "23505"
        _draft(connection, ids, document_id=ids["documents"][1], base_version_id=ids["versions"][1])
        assert connection.scalar(text("SELECT count(*) FROM document_drafts")) == 2
        connection.execute(text("UPDATE documents SET current_version_id=NULL"))
        with pytest.raises(IntegrityError) as deletion, connection.begin_nested():
            connection.execute(
                text("DELETE FROM document_versions WHERE id=:id"), {"id": ids["versions"][0]}
            )
        assert deletion.value.orig.sqlstate == "23503"
        assert connection.scalar(text("SELECT count(*) FROM document_drafts")) == 2
