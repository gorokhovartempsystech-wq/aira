"""Frozen D03-04 additive receipt schema, including preservation of V6 data."""

from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import BigInteger, Text, inspect, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from test_docx_storage_migrations import ROOT, V6, insert_row, legacy_state
from test_draft_migrations import V5, _draft, _seed_complete_history

V7 = "0007_docx_edit_receipts"


def columns(connection):
    return [
        {**c, "type": str(c["type"])} for c in inspect(connection).get_columns("docx_documents")
    ]


def test_additive_upgrade_repeat_downgrade_preserves_all_existing_data(
    empty_pg_engine,
    apply_migrations,
):
    apply_migrations(empty_pg_engine, V5)
    with empty_pg_engine.begin() as conn:
        ids = _seed_complete_history(conn)
        _draft(conn, ids)
        baseline = legacy_state(conn)
        project = conn.scalar(text("SELECT id FROM projects ORDER BY id LIMIT 1"))
    apply_migrations(empty_pg_engine, V6)
    with empty_pg_engine.begin() as conn:
        insert_row(conn, project)
        original = conn.execute(text("SELECT * FROM docx_documents")).all()
        schema = columns(conn)
    apply_migrations(empty_pg_engine, V7)
    apply_migrations(empty_pg_engine, V7)
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V7
        assert conn.execute(text("SELECT * FROM docx_documents")).all() == original
        assert columns(conn) == schema
        assert legacy_state(conn) == baseline
        assert set(inspect(conn).get_table_names()) == {
            *baseline,
            "docx_documents",
            "docx_edit_receipts",
            "alembic_version",
        }
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, V6)
        assert conn.execute(text("SELECT * FROM docx_documents")).all() == original
        assert legacy_state(conn) == baseline
        assert "docx_edit_receipts" not in inspect(conn).get_table_names()


def test_receipt_schema_and_model_match(pg_engine):
    model = getattr(import_module("ara.models"), "DocxEditReceipt")
    assert model.__table__ is import_module("ara.db").Base.metadata.tables["docx_edit_receipts"]
    inspector = inspect(pg_engine)
    columns = {c["name"]: c for c in inspector.get_columns("docx_edit_receipts")}
    assert set(columns) == {
        "document_id",
        "operation_id",
        "request_sha256",
        "title",
        "storage_revision",
        "current_sha256",
        "current_size_bytes",
        "document_created_at",
        "document_updated_at",
        "created_at",
    }
    assert all(not c["nullable"] for c in columns.values())
    for name in ("document_id", "operation_id"):
        assert isinstance(columns[name]["type"], UUID)
    for name in ("request_sha256", "title", "current_sha256"):
        assert isinstance(columns[name]["type"], Text)
    for name in ("storage_revision", "current_size_bytes"):
        assert isinstance(columns[name]["type"], BigInteger)
    for name in ("document_created_at", "document_updated_at", "created_at"):
        assert columns[name]["type"].timezone is True
    assert columns["created_at"]["default"] == "clock_timestamp()"
    assert all(c["default"] is None for name, c in columns.items() if name != "created_at")
    assert inspector.get_pk_constraint("docx_edit_receipts")["constrained_columns"] == [
        "document_id",
        "operation_id",
    ]
    (fk,) = inspector.get_foreign_keys("docx_edit_receipts")
    assert fk["referred_table"] == "docx_documents" and fk["referred_columns"] == ["id"]
    assert fk["options"].get("ondelete", "NO ACTION") in {"NO ACTION", "RESTRICT"}
    assert inspector.get_indexes("docx_edit_receipts") == []
    checks = inspector.get_check_constraints("docx_edit_receipts")
    assert all(c["name"] for c in checks)
    for field in (
        "request_sha256",
        "title",
        "storage_revision",
        "current_sha256",
        "current_size_bytes",
    ):
        assert any(field in c["sqltext"] for c in checks)


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_id": uuid4()},
        {"operation_id": None},
        {"request_sha256": "Z" * 64},
        {"current_sha256": "0" * 63},
        {"title": ""},
        {"title": "x" * 201},
        {"storage_revision": 1},
        {"current_size_bytes": 0},
        {"document_created_at": None},
    ],
)
def test_receipt_database_constraints(run_world, overrides):
    from test_docx_text_edit import seed

    item = seed(run_world)
    values = {
        "document_id": item.document_id,
        "operation_id": uuid4(),
        "request_sha256": "0" * 64,
        "title": item.title,
        "storage_revision": 2,
        "current_sha256": item.current_sha256,
        "current_size_bytes": len(item.current_data),
        "document_created_at": item.created_at,
        "document_updated_at": item.updated_at,
        **overrides,
    }
    with pytest.raises(IntegrityError):
        with run_world["engine"].begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO docx_edit_receipts ("
                    + ",".join(values)
                    + ") VALUES ("
                    + ",".join(":" + name for name in values)
                    + ")"
                ),
                values,
            )
