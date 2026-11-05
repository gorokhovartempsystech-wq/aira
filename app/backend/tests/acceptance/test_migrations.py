"""Independent PostgreSQL acceptance for T01-02; synthetic data only."""

import json
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Text, inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError

MARKDOWN = "## Условие\n\n| Поле | Значение |\n| --- | --- |\n| Имя | Свет |\n\n```json\n{}\n```\n"
BLOCKS = [{"id": "intro", "kind": "paragraph", "text": "Синтетический пример"}]
SOURCE_URL = "https://confluence.example.invalid/pages/viewpage.action?pageId=123"
PROVENANCE = {"source": "synthetic", "revision": 2}
OMISSIONS = [{"type": "image", "reason": "not imported"}]


def _execute(connection, statement, **parameters):
    return connection.execute(text(statement), parameters)


def _seed_documents(connection):
    ids = {
        key: uuid4()
        for key in (
            "owner",
            "other_owner",
            "project",
            "other_project",
            "document",
            "peer_document",
            "other_document",
            "first_version",
            "second_version",
            "peer_version",
            "other_version",
        )
    }
    for key in ("owner", "other_owner"):
        _execute(connection, "INSERT INTO users (id) VALUES (:id)", id=ids[key])
    for project, owner in (("project", "owner"), ("other_project", "other_owner")):
        _execute(
            connection,
            "INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, :name)",
            id=ids[project],
            owner=ids[owner],
            name="Synthetic project",
        )
    for document, project in (
        ("document", "project"),
        ("peer_document", "project"),
        ("other_document", "other_project"),
    ):
        _execute(
            connection,
            "INSERT INTO documents (id, project_id, title, source_url) "
            "VALUES (:id, :project, :title, :source)",
            id=ids[document],
            project=ids[project],
            title="Synthetic document",
            source=SOURCE_URL,
        )
    for version, document in (
        ("first_version", "document"),
        ("peer_version", "peer_document"),
        ("other_version", "other_document"),
    ):
        _execute(
            connection,
            "INSERT INTO document_versions (id, document_id, content_markdown) "
            "VALUES (:id, :document, :content)",
            id=ids[version],
            document=ids[document],
            content="Initial synthetic content\n",
        )
    _execute(
        connection,
        "INSERT INTO document_versions "
        "(id, document_id, parent_version_id, content_markdown, "
        "blocks, provenance, import_omissions) "
        "VALUES (:id, :document, :parent, :content, "
        "CAST(:blocks AS jsonb), CAST(:provenance AS jsonb), CAST(:omissions AS jsonb))",
        id=ids["second_version"],
        document=ids["document"],
        parent=ids["first_version"],
        content=MARKDOWN,
        blocks=json.dumps(BLOCKS),
        provenance=json.dumps(PROVENANCE),
        omissions=json.dumps(OMISSIONS),
    )
    for document, version in (
        ("document", "second_version"),
        ("peer_document", "peer_version"),
        ("other_document", "other_version"),
    ):
        _execute(
            connection,
            "UPDATE documents SET current_version_id = :version WHERE id = :document",
            version=ids[version],
            document=ids[document],
        )
    return ids


def _schema_signature(connection):
    inspector = inspect(connection)
    tables = {}
    for table in sorted(inspector.get_table_names(schema="public")):
        tables[table] = {
            "columns": [
                (column["name"], str(column["type"]), column["nullable"], column["default"])
                for column in inspector.get_columns(table, schema="public")
            ],
            "pk": inspector.get_pk_constraint(table, schema="public"),
            "fk": inspector.get_foreign_keys(table, schema="public"),
            "unique": inspector.get_unique_constraints(table, schema="public"),
            "check": inspector.get_check_constraints(table, schema="public"),
            "indexes": inspector.get_indexes(table, schema="public"),
        }
    return json.dumps(tables, sort_keys=True, default=str)


def test_empty_upgrade_is_repeatable_and_matches_orm(empty_pg_engine, apply_migrations):
    from ara.db import Base
    from ara.models import Document, DocumentVersion, Project, User

    assert {model.__tablename__ for model in (User, Project, Document, DocumentVersion)} == {
        "users",
        "projects",
        "documents",
        "document_versions",
    }
    apply_migrations(empty_pg_engine)
    with empty_pg_engine.connect() as connection:
        before = _schema_signature(connection)
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision
        assert (
            compare_metadata(
                MigrationContext.configure(
                    connection, opts={"compare_type": True, "compare_server_default": True}
                ),
                Base.metadata,
            )
            == []
        )
    apply_migrations(empty_pg_engine)
    with empty_pg_engine.connect() as connection:
        assert _schema_signature(connection) == before
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            revision
        )


def test_downgrade_base_then_upgrade_recreates_schema(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine)
    with empty_pg_engine.connect() as connection:
        original = _schema_signature(connection)
    apply_migrations(empty_pg_engine, revision="base")
    with empty_pg_engine.connect() as connection:
        assert set(inspect(connection).get_table_names(schema="public")) <= {"alembic_version"}
    apply_migrations(empty_pg_engine)
    with empty_pg_engine.connect() as connection:
        assert _schema_signature(connection) == original


def test_required_postgresql_types_defaults_and_indexes(pg_engine):
    inspector = inspect(pg_engine)
    required_columns = {
        "users": {"id", "created_at"},
        "projects": {"id", "owner_id", "name", "created_at"},
        "documents": {"id", "project_id", "title", "created_at"},
        "document_versions": {
            "id",
            "document_id",
            "content_markdown",
            "blocks",
            "provenance",
            "import_omissions",
            "created_at",
        },
    }
    for table, required in required_columns.items():
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert all(columns[name]["nullable"] is False for name in required)
        assert isinstance(columns["id"]["type"], UUID)
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        assert columns["created_at"]["nullable"] is False
        assert columns["created_at"]["type"].timezone is True
        assert columns["created_at"]["default"] is not None
    for table, leading_column in (
        ("projects", "owner_id"),
        ("documents", "project_id"),
        ("document_versions", "document_id"),
    ):
        assert any(
            index["column_names"][0] == leading_column for index in inspector.get_indexes(table)
        )
    versions = {column["name"]: column for column in inspector.get_columns("document_versions")}
    documents = {column["name"]: column for column in inspector.get_columns("documents")}
    assert isinstance(documents["source_url"]["type"], Text)
    assert documents["source_url"]["nullable"] is True
    for name in ("blocks", "provenance", "import_omissions"):
        assert isinstance(versions[name]["type"], JSONB)
        assert versions[name]["nullable"] is False
        assert versions[name]["default"] is not None
    assert any(
        constraint["column_names"] == ["document_id", "id"]
        for constraint in inspector.get_unique_constraints("document_versions")
    )


def test_versions_and_json_survive_commit_without_changing_history(pg_engine):
    with pg_engine.begin() as connection:
        ids = _seed_documents(connection)
    with pg_engine.connect() as connection:
        row = (
            _execute(
                connection,
                "SELECT u.id AS owner_id, d.current_version_id, d.source_url, v.* "
                "FROM document_versions v JOIN documents d ON d.id = v.document_id "
                "JOIN projects p ON p.id = d.project_id JOIN users u ON u.id = p.owner_id "
                "WHERE v.id = :version",
                version=ids["second_version"],
            )
            .mappings()
            .one()
        )
        assert row["owner_id"] == ids["owner"]
        assert row["source_url"] == SOURCE_URL
        assert row["current_version_id"] == ids["second_version"]
        assert row["parent_version_id"] == ids["first_version"]
        assert row["content_markdown"] == MARKDOWN
        assert row["blocks"] == BLOCKS
        assert row["provenance"] == PROVENANCE
        assert row["import_omissions"] == OMISSIONS
        assert row["created_at"].utcoffset() is not None
        first = _execute(
            connection,
            "SELECT content_markdown, blocks, provenance, import_omissions "
            "FROM document_versions WHERE id = :version",
            version=ids["first_version"],
        ).one()
        assert tuple(first) == ("Initial synthetic content\n", [], {}, [])


@pytest.mark.parametrize(
    ("statement", "bindings"),
    [
        (
            "INSERT INTO projects (id, owner_id, name) VALUES (:new, :missing, 'Synthetic')",
            {},
        ),
        (
            "INSERT INTO documents (id, project_id, title) VALUES (:new, :missing, 'Synthetic')",
            {},
        ),
        (
            "INSERT INTO document_versions (id, document_id, content_markdown) "
            "VALUES (:new, :missing, 'Synthetic')",
            {},
        ),
        (
            "UPDATE documents SET current_version_id = :version WHERE id = :document",
            {"version": "peer_version"},
        ),
        (
            "UPDATE documents SET current_version_id = :version WHERE id = :document",
            {"version": "other_version"},
        ),
        (
            "UPDATE document_versions SET parent_version_id = :parent WHERE id = :second_version",
            {"parent": "peer_version"},
        ),
        (
            "UPDATE document_versions SET parent_version_id = :parent WHERE id = :second_version",
            {"parent": "other_version"},
        ),
        (
            "UPDATE document_versions SET parent_version_id = id WHERE id = :first_version",
            {},
        ),
    ],
    ids=[
        "orphan-owner",
        "orphan-project",
        "orphan-document",
        "current-other-document-same-owner",
        "current-other-owner",
        "parent-other-document-same-owner",
        "parent-other-owner",
        "self-parent",
    ],
)
def test_database_rejects_broken_relationships(pg_engine, statement, bindings):
    with pg_engine.begin() as connection:
        ids = _seed_documents(connection)
        parameters = {**ids, "new": uuid4(), "missing": uuid4()}
        parameters.update({name: ids[key] for name, key in bindings.items()})
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                _execute(connection, statement, **parameters)
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert connection.execute(text("SELECT count(*) FROM document_versions")).scalar_one() == 4


@pytest.mark.parametrize(
    ("column", "invalid_json"),
    [
        ("blocks", "{}"),
        ("provenance", "[]"),
        ("import_omissions", "{}"),
        ("blocks", "null"),
        ("provenance", "null"),
        ("import_omissions", "null"),
        ("blocks", None),
        ("provenance", None),
        ("import_omissions", None),
    ],
)
def test_database_rejects_wrong_json_shapes_and_nulls(pg_engine, column, invalid_json):
    with pg_engine.begin() as connection:
        ids = _seed_documents(connection)
        # Column names are fixed by parametrization; values always use bind parameters.
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                _execute(
                    connection,
                    f"UPDATE document_versions SET {column} = CAST(:value AS jsonb) "
                    "WHERE id = :version",
                    value=invalid_json,
                    version=ids["second_version"],
                )


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("users", "owner"),
        ("projects", "project"),
        ("documents", "document"),
        ("document_versions", "first_version"),
        ("document_versions", "second_version"),
    ],
)
def test_deleting_referenced_rows_cannot_cascade_away_history(pg_engine, table, key):
    with pg_engine.begin() as connection:
        ids = _seed_documents(connection)
        # Fixed table names, synthetic bound UUIDs, and an isolated rollback per rejection.
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                _execute(connection, f"DELETE FROM {table} WHERE id = :id", id=ids[key])
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert connection.execute(text("SELECT count(*) FROM document_versions")).scalar_one() == 4
        assert connection.execute(text("SELECT count(*) FROM documents")).scalar_one() == 3
