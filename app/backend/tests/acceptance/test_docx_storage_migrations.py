"""D02-06 schema and preservation of all pre-existing PostgreSQL tables."""

from hashlib import sha256
from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from docx_storage_fixtures import raw
from sqlalchemy import BigInteger, Text, inspect, text
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.exc import IntegrityError
from test_analysis_run_migrations import ROOT
from test_draft_migrations import V5, _draft, _seed_complete_history, _snapshot

V6 = "0006_docx_documents"


def legacy_state(connection):
    inspector = inspect(connection)
    result = _snapshot(connection)
    result["document_drafts"] = {
        "rows": connection.execute(
            text("SELECT * FROM document_drafts ORDER BY document_id")
        ).all(),
        "columns": [
            (c["name"], str(c["type"]), c["nullable"], c["default"])
            for c in inspector.get_columns("document_drafts")
        ],
        "pk": inspector.get_pk_constraint("document_drafts"),
        "foreign_keys": inspector.get_foreign_keys("document_drafts"),
        "unique": inspector.get_unique_constraints("document_drafts"),
        "checks": inspector.get_check_constraints("document_drafts"),
        "indexes": inspector.get_indexes("document_drafts"),
    }
    return result


def insert_row(connection, owner_project_id, **overrides):
    data = raw()
    values = {
        "id": uuid4(),
        "project_id": owner_project_id,
        "title": "Synthetic DOCX",
        "original_data": data,
        "original_sha256": sha256(data).hexdigest(),
        "current_data": data,
        "current_sha256": sha256(data).hexdigest(),
        "storage_revision": 1,
        **overrides,
    }
    connection.execute(
        text(
            "INSERT INTO docx_documents "
            "(id,project_id,title,original_data,original_sha256,current_data,current_sha256,"
            "storage_revision) VALUES (:id,:project_id,:title,:original_data,:original_sha256,"
            ":current_data,:current_sha256,:storage_revision)"
        ),
        values,
    )


def test_upgrade_repeat_downgrade_preserves_all_nine_existing_tables(
    empty_pg_engine, apply_migrations
):
    apply_migrations(empty_pg_engine, V5)
    with empty_pg_engine.begin() as conn:
        ids = _seed_complete_history(conn)
        _draft(conn, ids)
        baseline = legacy_state(conn)
        assert len(baseline) == 9 and all(value["rows"] for value in baseline.values())
        project = conn.scalar(text("SELECT id FROM projects ORDER BY id LIMIT 1"))
    apply_migrations(empty_pg_engine, V6)
    with empty_pg_engine.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V6
        assert legacy_state(conn) == baseline
        assert set(inspect(conn).get_table_names()) == {
            *baseline,
            "docx_documents",
            "alembic_version",
        }
        insert_row(conn, project)
        row = conn.execute(text("SELECT * FROM docx_documents")).one()
    apply_migrations(empty_pg_engine, V6)
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V6
        assert legacy_state(conn) == baseline
        assert conn.execute(text("SELECT * FROM docx_documents")).one() == row
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, V5)
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V5
        assert legacy_state(conn) == baseline
        assert set(inspect(conn).get_table_names()) == {*baseline, "alembic_version"}
    apply_migrations(empty_pg_engine, V6)
    with empty_pg_engine.connect() as conn:
        assert legacy_state(conn) == baseline
        assert conn.scalar(text("SELECT count(*) FROM docx_documents")) == 0


def test_model_and_migration_have_exact_columns_constraints_and_pagination_index(pg_engine):
    model = getattr(import_module("ara.models"), "DocxDocument")
    metadata = import_module("ara.db").Base.metadata
    assert model.__tablename__ == "docx_documents"
    assert model.__table__ is metadata.tables["docx_documents"]
    inspector = inspect(pg_engine)
    columns = {c["name"]: c for c in inspector.get_columns("docx_documents")}
    assert set(columns) == {
        "id",
        "project_id",
        "title",
        "original_data",
        "original_sha256",
        "current_data",
        "current_sha256",
        "storage_revision",
        "created_at",
        "updated_at",
    }
    assert all(not c["nullable"] for c in columns.values())
    for name in ("id", "project_id"):
        assert isinstance(columns[name]["type"], UUID)
    for name in ("title", "original_sha256", "current_sha256"):
        assert isinstance(columns[name]["type"], Text)
    for name in ("original_data", "current_data"):
        assert isinstance(columns[name]["type"], BYTEA)
    assert isinstance(columns["storage_revision"]["type"], BigInteger)
    for name in ("id", "storage_revision"):
        assert columns[name]["default"] is None
        assert model.__table__.c[name].default is None
    for name in ("created_at", "updated_at"):
        assert columns[name]["type"].timezone is True
        assert columns[name]["default"] == "clock_timestamp()"
    assert inspector.get_pk_constraint("docx_documents")["constrained_columns"] == ["id"]
    foreign = inspector.get_foreign_keys("docx_documents")
    assert len(foreign) == 1
    assert foreign[0]["name"] and foreign[0]["constrained_columns"] == ["project_id"]
    assert foreign[0]["referred_table"] == "projects" and foreign[0]["referred_columns"] == ["id"]
    assert foreign[0]["options"].get("ondelete", "NO ACTION") in {"NO ACTION", "RESTRICT"}
    checks = inspector.get_check_constraints("docx_documents")
    assert all(check["name"] for check in checks)
    for field in (
        "title",
        "original_data",
        "current_data",
        "original_sha256",
        "current_sha256",
        "storage_revision",
    ):
        assert any(field in check["sqltext"] for check in checks)
    indexes = inspector.get_indexes("docx_documents")
    assert len(indexes) == 1 and indexes[0]["unique"] is False
    assert indexes[0]["column_names"] == ["project_id", "created_at", "id"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "x" * 201},
        {"title": None},
        {"original_data": b""},
        {"current_data": b""},
        {"current_data": None},
        {"original_sha256": "A" * 64},
        {"current_sha256": "g" * 64},
        {"current_sha256": "0" * 63},
        {"original_sha256": None},
        {"storage_revision": 0},
        {"storage_revision": -1},
        {"storage_revision": None},
        {"project_id": uuid4()},
    ],
)
def test_database_rejects_invalid_storage_rows(pg_engine, overrides):
    getattr(import_module("ara.models"), "DocxDocument")
    owner, project = uuid4(), uuid4()
    with pg_engine.begin() as conn:
        conn.execute(text("INSERT INTO users(id) VALUES (:id)"), {"id": owner})
        conn.execute(
            text("INSERT INTO projects(id,owner_id,name) VALUES (:id,:owner,'Synthetic')"),
            {"id": project, "owner": owner},
        )
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as conn:
            insert_row(conn, project, **overrides)
    with pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_documents")) == 0
