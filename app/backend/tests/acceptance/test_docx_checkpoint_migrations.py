"""Frozen D03-16B1: additive schema, NULL gates and preservation on downgrade."""

import json
from dataclasses import asdict
from hashlib import sha256
from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from docx_storage_fixtures import raw
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_docx_storage_migrations import insert_row
from test_draft_migrations import _draft, _seed_complete_history
from test_migrations import _schema_signature

from ara.docx_package.projection import project_docx

V8, V9 = "0008_docx_edit_drafts", "0009_docx_editor_checkpoints"
TABLE = "docx_editor_checkpoints"


def downgrade(engine):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, V8)


def seed_v8(engine):
    with engine.begin() as conn:
        ids = _seed_complete_history(conn)
        _draft(conn, ids)
        project = conn.scalar(text("SELECT id FROM projects ORDER BY id LIMIT 1"))
        document_id = uuid4()
        insert_row(conn, project, id=document_id, storage_revision=2)
        data = raw()
        span = project_docx(data).blocks[0].spans[0]
        payload = {
            "edit": {
                "expected_storage_revision": "2",
                "anchor": {**asdict(span.anchor), "path": list(span.anchor.path)},
                "expected_text": span.text,
                "replacement_text": "Synthetic replacement",
            },
            "operation_id": None,
        }
        # Validate a real legacy payload, not a placeholder that only fits JSONB.
        from ara.docx_documents.recovery_schemas import RecoveryPayload

        RecoveryPayload.model_validate(payload)
        conn.execute(
            text(
                "INSERT INTO docx_edit_drafts "
                "VALUES (:id,:token,CAST(:p AS jsonb),clock_timestamp())"
            ),
            {"id": document_id, "token": uuid4(), "p": json.dumps(payload)},
        )
        conn.execute(
            text("""
            INSERT INTO docx_edit_receipts
            (document_id,operation_id,request_sha256,title,storage_revision,current_sha256,
             current_size_bytes,document_created_at,document_updated_at)
            SELECT id,:op,:hash,title,storage_revision,current_sha256,octet_length(current_data),
                   created_at,updated_at FROM docx_documents WHERE id=:id
        """),
            {"id": document_id, "op": uuid4(), "hash": "a" * 64},
        )
    return document_id


def previous(conn):
    tables = [t for t in inspect(conn).get_table_names() if t not in (TABLE, "alembic_version")]
    schema = json.loads(_schema_signature(conn))
    schema.pop(TABLE, None)
    return schema, {t: conn.execute(text(f'SELECT * FROM "{t}"')).all() for t in tables}


def row(document_id, phase="empty", **overrides):
    values = {
        "document_id": document_id,
        "checkpoint_revision": 1,
        "format_version": 1,
        "phase": phase,
        "base_storage_revision": None,
        "base_sha256": None,
        "working_data": None,
        "working_sha256": None,
        "metadata": None,
        "last_request_id": None,
        "last_request_sha256": None,
    }
    if phase != "empty":
        values.update(
            base_storage_revision=2,
            base_sha256="a" * 64,
            working_data=b"x",
            working_sha256=sha256(b"x").hexdigest(),
            metadata={"pending": None if phase == "working" else {"operation_id": str(uuid4())}},
        )
    values.update(overrides)
    return values


def insert(conn, values):
    prepared = {
        **values,
        "metadata": json.dumps(values["metadata"]) if values["metadata"] is not None else None,
    }
    columns = ",".join(values)
    binds = ",".join(
        "CAST(:metadata AS jsonb)" if key == "metadata" else ":" + key for key in values
    )
    conn.execute(text(f"INSERT INTO {TABLE} ({columns}) VALUES ({binds})"), prepared)


def test_upgrade_repeat_clean_downgrade_preserves_all_v8_data(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine, V8)
    document_id = seed_v8(empty_pg_engine)
    with empty_pg_engine.connect() as conn:
        before = previous(conn)
    apply_migrations(empty_pg_engine, V9)
    apply_migrations(empty_pg_engine, V9)
    with empty_pg_engine.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V9
        assert previous(conn) == before
        insert(conn, row(document_id, last_request_id=uuid4(), last_request_sha256="b" * 64))
    downgrade(empty_pg_engine)
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V8
        assert TABLE not in inspect(conn).get_table_names() and previous(conn) == before
    apply_migrations(empty_pg_engine, V9)
    with empty_pg_engine.connect() as conn:
        assert previous(conn) == before and conn.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 0


def test_exact_columns_model_primary_and_foreign_keys(pg_engine):
    model = getattr(import_module("ara.models"), "DocxEditorCheckpoint")
    with pg_engine.connect() as conn:
        inspector = inspect(conn)
        cols = {c["name"]: c for c in inspector.get_columns(TABLE)}
        assert set(cols) == set(row(uuid4())) | {"updated_at"}
        expected = {
            "document_id": "UUID",
            "checkpoint_revision": "BIGINT",
            "format_version": "SMALLINT",
            "phase": "TEXT",
            "base_storage_revision": "BIGINT",
            "base_sha256": "TEXT",
            "working_data": "BYTEA",
            "working_sha256": "TEXT",
            "metadata": "JSONB",
            "last_request_id": "UUID",
            "last_request_sha256": "TEXT",
            "updated_at": "TIMESTAMP",
        }
        assert {k: str(c["type"]) for k, c in cols.items()} == expected
        assert {k for k, c in cols.items() if not c["nullable"]} == {
            "document_id",
            "checkpoint_revision",
            "format_version",
            "phase",
            "updated_at",
        }
        assert cols["updated_at"]["type"].timezone
        assert cols["updated_at"]["default"] == "clock_timestamp()"
        assert all(c["default"] is None for k, c in cols.items() if k != "updated_at")
        assert inspector.get_pk_constraint(TABLE)["constrained_columns"] == ["document_id"]
        fk = inspector.get_foreign_keys(TABLE)
        assert len(fk) == 1 and fk[0]["referred_table"] == "docx_documents"
        assert fk[0]["options"].get("ondelete") is None
        assert model.checkpoint_metadata.property.columns[0].name == "metadata"
        assert model.__table__ is import_module("ara.db").Base.metadata.tables[TABLE]


@pytest.mark.parametrize("phase", ["working", "pending"])
def test_downgrade_refuses_unsaved_work_atomically(empty_pg_engine, apply_migrations, phase):
    apply_migrations(empty_pg_engine, V8)
    document_id = seed_v8(empty_pg_engine)
    apply_migrations(empty_pg_engine, V9)
    with empty_pg_engine.begin() as conn:
        insert(conn, row(document_id, phase))
        before = conn.execute(text(f"SELECT * FROM {TABLE}")).all(), previous(conn)
    with pytest.raises(RuntimeError):
        downgrade(empty_pg_engine)
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V9
        assert (conn.execute(text(f"SELECT * FROM {TABLE}")).all(), previous(conn)) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"checkpoint_revision": 0},
        {"format_version": 2},
        {"phase": "unknown"},
        {"base_storage_revision": 0},
        {"base_sha256": "A" * 64},
        {"working_sha256": "z" * 64},
        {"working_data": b""},
        {"metadata": []},
        {"metadata": {}},
        {"metadata": {"pending": {}}},
        {"last_request_id": uuid4()},
        {"last_request_sha256": "a" * 64},
        {"last_request_id": uuid4(), "last_request_sha256": "invalid"},
        {"base_sha256": None},
        {"metadata": None},
    ],
)
def test_database_rejects_invalid_working_shape_and_unknown_nulls(pg_engine, changes):
    # No parent is required for invalid rows: CHECK must fail before the FK gate.
    with pg_engine.connect() as conn, conn.begin():
        with pytest.raises(IntegrityError) as caught:
            values = row(uuid4(), "working")
            values.update(changes)
            insert(conn, values)
        assert caught.value.orig.sqlstate == "23514"
