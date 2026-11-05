"""Independent T02-02 schema gate, using synthetic rows in disposable PostgreSQL."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, Text, inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
OLD_TABLES = ("users", "projects", "documents", "document_versions")
NEW_TABLES = {"context_revisions", "analysis_runs"}
CONTEXT = [{"id": "clarification", "role": "user_clarification", "text": "  Точный текст\r\n"}]


@pytest.fixture
def pg_engine(empty_pg_engine, apply_migrations):
    """Keep this historical schema gate pinned to the immutable T02-02 revision."""
    apply_migrations(empty_pg_engine, "0002_analysis_runs")
    return empty_pg_engine


def _seed_history(connection):
    ids = {name: [uuid4(), uuid4()] for name in ("owners", "projects", "documents", "versions")}
    for index in range(2):
        connection.execute(
            text("INSERT INTO users (id) VALUES (:id)"), {"id": ids["owners"][index]}
        )
        connection.execute(
            text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'Synthetic')"),
            {"id": ids["projects"][index], "owner": ids["owners"][index]},
        )
        connection.execute(
            text("INSERT INTO documents (id, project_id, title) VALUES (:id, :project, 'Тест')"),
            {"id": ids["documents"][index], "project": ids["projects"][index]},
        )
        connection.execute(
            text(
                "INSERT INTO document_versions (id, document_id, content_markdown, blocks) "
                "VALUES (:id, :document, :content, CAST(:blocks AS jsonb))"
            ),
            {
                "id": ids["versions"][index],
                "document": ids["documents"][index],
                "content": "# История\r\n\r\n  Original  text\r\n",
                "blocks": json.dumps([{"id": "b1", "kind": "heading", "text": "# История\r\n"}]),
            },
        )
        connection.execute(
            text("UPDATE documents SET current_version_id = :version WHERE id = :id"),
            {"id": ids["documents"][index], "version": ids["versions"][index]},
        )
    return ids


def _context(connection, ids, *, document=0, owner=0, items=None):
    context_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO context_revisions (id, document_id, owner_id, items) "
            "VALUES (:id, :document, :owner, CAST(:items AS jsonb))"
        ),
        {
            "id": context_id,
            "document": ids["documents"][document],
            "owner": ids["owners"][owner],
            "items": json.dumps(CONTEXT if items is None else items),
        },
    )
    return context_id


def _run(connection, ids, context_id, **overrides):
    row = {
        "id": uuid4(),
        "owner_id": ids["owners"][0],
        "document_id": ids["documents"][0],
        "base_version_id": ids["versions"][0],
        "context_revision_id": context_id,
        "mode": "lint",
        "idempotency_key": "schema-" + uuid4().hex,
        "request_fingerprint": "a" * 64,
        "request_payload": {"synthetic": "  Снимок\r\n"},
        **overrides,
    }
    columns = ", ".join(row)
    placeholders = ", ".join(
        f"CAST(:{name} AS jsonb)" if name == "request_payload" else f":{name}" for name in row
    )
    parameters = {**row, "request_payload": json.dumps(row["request_payload"])}
    connection.execute(
        text(f"INSERT INTO analysis_runs ({columns}) VALUES ({placeholders})"), parameters
    )
    return row["id"]


def _old_snapshot(connection):
    inspector = inspect(connection)
    return {
        table: {
            "rows": connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all(),
            "columns": [
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns(table)
            ],
            "foreign_keys": inspector.get_foreign_keys(table),
            "unique": inspector.get_unique_constraints(table),
            "checks": inspector.get_check_constraints(table),
            "indexes": inspector.get_indexes(table),
        }
        for table in OLD_TABLES
    }


def test_historical_upgrade_and_downgrade_preserve_document_history(
    empty_pg_engine, apply_migrations
):
    apply_migrations(empty_pg_engine, "0001_initial_documents")
    with empty_pg_engine.begin() as connection:
        ids = _seed_history(connection)
        before = _old_snapshot(connection)
    apply_migrations(empty_pg_engine, "0002_analysis_runs")
    with empty_pg_engine.begin() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0002_analysis_runs"
        )
        assert _old_snapshot(connection) == before
        context_id = _context(connection, ids)
        run_id = _run(connection, ids, context_id)
        run = (
            connection.execute(text("SELECT * FROM analysis_runs WHERE id = :id"), {"id": run_id})
            .mappings()
            .one()
        )
        assert run["status"] == "queued"
        assert run["execution_mode"] == "fixture"
        assert run["has_import_omissions"] is False
        assert run["created_at"].utcoffset() is not None
        assert run["request_payload"] == {"synthetic": "  Снимок\r\n"}
    apply_migrations(empty_pg_engine, "0002_analysis_runs")
    with empty_pg_engine.connect() as connection:
        assert _old_snapshot(connection) == before
        assert connection.execute(text("SELECT id FROM analysis_runs")).scalar_one() == run_id

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_pg_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_initial_documents")
        assert _old_snapshot(connection) == before
        assert set(inspect(connection).get_table_names()) == {*OLD_TABLES, "alembic_version"}
    apply_migrations(empty_pg_engine, "0002_analysis_runs")
    with empty_pg_engine.connect() as connection:
        assert _old_snapshot(connection) == before
        assert NEW_TABLES <= set(inspect(connection).get_table_names())
        assert connection.execute(text("SELECT count(*) FROM analysis_runs")).scalar_one() == 0


def test_models_are_registered_and_new_columns_have_required_types(pg_engine):
    from ara.db import Base
    from ara.models import AnalysisRun, ContextRevision

    assert {AnalysisRun.__tablename__, ContextRevision.__tablename__} == NEW_TABLES
    assert all(
        model.__table__ is Base.metadata.tables[model.__tablename__]
        for model in (AnalysisRun, ContextRevision)
    )
    inspector = inspect(pg_engine)
    expected = {
        "context_revisions": {"id", "created_at", "document_id", "owner_id", "items"},
        "analysis_runs": {
            "id",
            "created_at",
            "owner_id",
            "document_id",
            "base_version_id",
            "context_revision_id",
            "mode",
            "status",
            "execution_mode",
            "idempotency_key",
            "request_fingerprint",
            "request_payload",
            "has_import_omissions",
        },
    }
    for table, names in expected.items():
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert set(columns) == names
        assert all(not column["nullable"] for column in columns.values())
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        for name, column in columns.items():
            if name == "id" or name.endswith("_id"):
                assert isinstance(column["type"], UUID)
        assert columns["created_at"]["type"].timezone is True
        assert columns["created_at"]["default"] is not None
        for foreign_key in inspector.get_foreign_keys(table):
            assert foreign_key["options"].get("ondelete", "NO ACTION") in {"NO ACTION", "RESTRICT"}
    runs = {column["name"]: column for column in inspector.get_columns("analysis_runs")}
    assert isinstance(runs["request_payload"]["type"], JSONB)
    assert isinstance(runs["has_import_omissions"]["type"], Boolean)
    for name in ("mode", "status", "execution_mode", "idempotency_key", "request_fingerprint"):
        assert isinstance(runs[name]["type"], Text)
    contexts = {column["name"]: column for column in inspector.get_columns("context_revisions")}
    assert isinstance(contexts["items"]["type"], JSONB)
    assert any(
        constraint["column_names"] == ["document_id", "owner_id", "id"]
        for constraint in inspector.get_unique_constraints("context_revisions")
    )
    assert any(
        constraint["column_names"] == ["owner_id", "idempotency_key"] and constraint["name"]
        for constraint in inspector.get_unique_constraints("analysis_runs")
    )
    indexes = [index["column_names"] for index in inspector.get_indexes("analysis_runs")]
    for leading in ("document_id", "owner_id", "context_revision_id"):
        assert any(columns[0] == leading for columns in indexes)
    assert any(columns[:2] == ["status", "created_at"] for columns in indexes)
    for table, required in (
        (
            "context_revisions",
            {
                (("document_id",), "documents", ("id",)),
                (("owner_id",), "users", ("id",)),
            },
        ),
        (
            "analysis_runs",
            {
                (("document_id",), "documents", ("id",)),
                (("owner_id",), "users", ("id",)),
                (("document_id", "base_version_id"), "document_versions", ("document_id", "id")),
                (
                    ("document_id", "owner_id", "context_revision_id"),
                    "context_revisions",
                    ("document_id", "owner_id", "id"),
                ),
            },
        ),
    ):
        actual = {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
            )
            for foreign_key in inspector.get_foreign_keys(table)
        }
        assert required <= actual


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "invalid"},
        {"status": "completed"},
        {"execution_mode": "real"},
        {"idempotency_key": ""},
        {"idempotency_key": "a" * 129},
        {"request_fingerprint": "a" * 63},
        {"request_fingerprint": "a" * 65},
        {"request_fingerprint": "A" * 64},
        {"request_fingerprint": "g" * 64},
        {"request_payload": []},
        {"request_payload": None},
        {"owner_id": None},
        {"base_version_id": None},
        {"context_revision_id": None},
    ],
)
def test_run_schema_rejects_invalid_persisted_values(pg_engine, overrides):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        context_id = _context(connection, ids)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _run(connection, ids, context_id, **overrides)
        assert connection.execute(text("SELECT count(*) FROM analysis_runs")).scalar_one() == 0


@pytest.mark.parametrize("items", [{}, "invalid", 12])
def test_context_items_must_be_json_array(pg_engine, items):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _context(connection, ids, items=items)


def test_context_items_reject_sql_and_json_null(pg_engine):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        context_id = _context(connection, ids)
        for value in (None, "null"):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE context_revisions SET items = CAST(:value AS jsonb) WHERE id = :id"
                    ),
                    {"id": context_id, "value": value},
                )


def test_composite_foreign_keys_reject_cross_document_owner_and_missing_rows(pg_engine):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        context_id = _context(connection, ids)
        wrong_document = _context(connection, ids, document=1)
        wrong_owner = _context(connection, ids, owner=1)
        for overrides in (
            {"base_version_id": ids["versions"][1]},
            {"context_revision_id": wrong_document},
            {"context_revision_id": wrong_owner},
            {"context_revision_id": uuid4()},
            {"base_version_id": uuid4()},
            {"document_id": uuid4()},
            {"owner_id": uuid4()},
        ):
            with pytest.raises(IntegrityError), connection.begin_nested():
                _run(connection, ids, context_id, **overrides)
        for column in ("owner_id", "document_id"):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(f"UPDATE context_revisions SET {column} = :missing WHERE id = :id"),
                    {"missing": uuid4(), "id": context_id},
                )


def test_key_is_unique_per_owner_and_stored_history_cannot_cascade_delete(pg_engine):
    with pg_engine.begin() as connection:
        ids = _seed_history(connection)
        context_id = _context(connection, ids)
        run_id = _run(connection, ids, context_id, idempotency_key="same-key")
        with pytest.raises(IntegrityError) as duplicate, connection.begin_nested():
            _run(connection, ids, context_id, idempotency_key="same-key")
        unique_name = duplicate.value.orig.diag.constraint_name
        assert unique_name in {
            constraint["name"]
            for constraint in inspect(connection).get_unique_constraints("analysis_runs")
            if constraint["column_names"] == ["owner_id", "idempotency_key"]
        }
        other_context = _context(connection, ids, owner=1)
        _run(
            connection,
            ids,
            other_context,
            owner_id=ids["owners"][1],
            idempotency_key="same-key",
        )
        for status in ("queued", "running", "succeeded", "failed"):
            _run(connection, ids, context_id, status=status, idempotency_key=uuid4().hex)
        _run(connection, ids, context_id, idempotency_key="a" * 128, mode="merge")
        for table, row_id in (
            ("context_revisions", context_id),
            ("document_versions", ids["versions"][0]),
            ("documents", ids["documents"][0]),
            ("users", ids["owners"][0]),
        ):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
        assert (
            connection.execute(
                text("SELECT id FROM analysis_runs WHERE id = :id"), {"id": run_id}
            ).scalar_one()
            == run_id
        )
        assert (
            connection.execute(
                text("SELECT items FROM context_revisions WHERE id = :id"), {"id": context_id}
            ).scalar_one()
            == CONTEXT
        )
