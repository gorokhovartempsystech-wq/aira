"""Independent T03-01 schema/history checks using disposable PostgreSQL only."""

import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Integer, Text, inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from test_analysis_run_migrations import ROOT, _context, _run
from test_worker_migrations import _attempt, _seed_run

V3 = "0003_worker_execution"
V4 = "0004_review_revisions"
OLD_TABLES = (
    "users",
    "projects",
    "documents",
    "document_versions",
    "context_revisions",
    "analysis_runs",
    "analysis_attempts",
)
DECISIONS = [
    {
        "group_id": "g1",
        "decision": "accepted",
        "edits": [{"patch_index": 0, "new_block_index": 0, "text": "  Сохранить\r\nтекст  "}],
    }
]


def _review(connection, related_run, owner, *, parent=None, number=1, **overrides):
    row = {
        "id": uuid4(),
        "run_id": related_run,
        "owner_id": owner,
        "parent_revision_id": parent,
        "revision_number": number,
        "result_fingerprint": "1a" * 32,
        "decisions": DECISIONS,
        **overrides,
    }
    columns = ", ".join(row)
    placeholders = ", ".join(
        "CAST(:decisions AS jsonb)" if name == "decisions" else f":{name}" for name in row
    )
    connection.execute(
        text(f"INSERT INTO review_revisions ({columns}) VALUES ({placeholders})"),
        {**row, "decisions": json.dumps(row["decisions"])},
    )
    return row["id"]


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


def _assert_old_preserved(before, after):
    for table, original in before.items():
        current = after[table]
        for key in ("rows", "columns", "pk", "foreign_keys", "checks"):
            assert current[key] == original[key]
        if table != "analysis_runs":
            assert current == original
            continue
        for key in ("unique", "indexes"):
            assert all(item in current[key] for item in original[key])
            added = [item for item in current[key] if item not in original[key]]
            assert len(added) == 1
            assert added[0]["column_names"] == ["id", "owner_id"]
            assert added[0]["name"]
            if key == "indexes":
                assert added[0]["unique"]


def test_review_upgrade_repeat_downgrade_preserves_worker_and_document_history(
    empty_pg_engine, apply_migrations
):
    apply_migrations(empty_pg_engine, V3)
    with empty_pg_engine.begin() as connection:
        ids, queued_run = _seed_run(connection)
        completed_run = _run(connection, ids, _context(connection, ids))
        attempt_id = _attempt(connection, ids, completed_run)
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
                "deadline_at=clock_timestamp()+interval '1 minute', "
                "completed_at=clock_timestamp(), incomplete_review=false, "
                "result_payload=CAST(:payload AS jsonb) WHERE id=:id"
            ),
            {"id": completed_run, "payload": json.dumps({"synthetic": "  результат\r\n"})},
        )
        before = _snapshot(connection)
    apply_migrations(empty_pg_engine, V4)
    with empty_pg_engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V4
        after = _snapshot(connection)
        _assert_old_preserved(before, after)
        first = _review(connection, completed_run, ids["owners"][0])
        second = _review(connection, completed_run, ids["owners"][0], parent=first, number=2)
        reviews = connection.execute(
            text("SELECT * FROM review_revisions ORDER BY revision_number")
        ).all()
    apply_migrations(empty_pg_engine, V4)
    with empty_pg_engine.connect() as connection:
        assert _snapshot(connection) == after
        assert (
            connection.execute(
                text("SELECT * FROM review_revisions ORDER BY revision_number")
            ).all()
            == reviews
        )

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_pg_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, V3)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V3
        assert _snapshot(connection) == before
        assert set(inspect(connection).get_table_names()) == {*OLD_TABLES, "alembic_version"}
    apply_migrations(empty_pg_engine, V4)
    with empty_pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V4
        _assert_old_preserved(before, _snapshot(connection))
        assert connection.scalar(text("SELECT count(*) FROM review_revisions")) == 0
        assert set(connection.scalars(text("SELECT id FROM analysis_runs"))) == {
            queued_run,
            completed_run,
        }
        assert first != second


def test_review_model_types_constraints_and_indexes(pg_engine):
    from ara.db import Base
    from ara.models import ReviewRevision

    assert ReviewRevision.__tablename__ == "review_revisions"
    assert ReviewRevision.__table__ is Base.metadata.tables["review_revisions"]
    inspector = inspect(pg_engine)
    columns = {column["name"]: column for column in inspector.get_columns("review_revisions")}
    assert set(columns) == {
        "id",
        "created_at",
        "run_id",
        "owner_id",
        "parent_revision_id",
        "revision_number",
        "result_fingerprint",
        "decisions",
    }
    assert {name for name, column in columns.items() if column["nullable"]} == {
        "parent_revision_id"
    }
    for name in ("id", "run_id", "owner_id", "parent_revision_id"):
        assert isinstance(columns[name]["type"], UUID)
    assert isinstance(columns["revision_number"]["type"], Integer)
    assert isinstance(columns["result_fingerprint"]["type"], Text)
    assert isinstance(columns["decisions"]["type"], JSONB)
    assert columns["created_at"]["type"].timezone is True
    assert columns["created_at"]["default"] is not None
    assert inspector.get_pk_constraint("review_revisions")["constrained_columns"] == ["id"]
    unique = [item["column_names"] for item in inspector.get_unique_constraints("review_revisions")]
    assert ["run_id", "revision_number"] in unique
    assert ["run_id", "owner_id", "id"] in unique
    assert ["run_id", "owner_id", "parent_revision_id"] in unique
    assert any(
        item["column_names"] == ["id", "owner_id"] and item["name"]
        for item in inspector.get_unique_constraints("analysis_runs")
    )
    foreign_keys = inspector.get_foreign_keys("review_revisions")
    assert {
        (("owner_id",), "users", ("id",)),
        (("run_id", "owner_id"), "analysis_runs", ("id", "owner_id")),
        (
            ("run_id", "owner_id", "parent_revision_id"),
            "review_revisions",
            ("run_id", "owner_id", "id"),
        ),
    } <= {
        (
            tuple(item["constrained_columns"]),
            item["referred_table"],
            tuple(item["referred_columns"]),
        )
        for item in foreign_keys
    }
    assert all(
        item["options"].get("ondelete", "NO ACTION") in {"NO ACTION", "RESTRICT"}
        for item in foreign_keys
    )
    indexes = inspector.get_indexes("review_revisions")
    assert any(item["column_names"][0] == "owner_id" for item in indexes)
    root_indexes = [
        item
        for item in indexes
        if item["unique"]
        and item["column_names"] == ["run_id"]
        and item.get("dialect_options", {}).get("postgresql_where")
    ]
    assert len(root_indexes) == 1
    predicate = root_indexes[0]["dialect_options"]["postgresql_where"].lower()
    assert "parent_revision_id" in predicate and "is null" in predicate


@pytest.mark.parametrize(
    "overrides",
    [
        {"revision_number": 0},
        {"revision_number": -1},
        {"revision_number": 2},
        {"result_fingerprint": "a" * 63},
        {"result_fingerprint": "a" * 65},
        {"result_fingerprint": "A" * 64},
        {"result_fingerprint": "g" * 64},
        {"result_fingerprint": None},
        {"decisions": {}},
        {"decisions": None},
        {"decisions": "not-array"},
        {"owner_id": None},
        {"run_id": None},
        {"owner_id": uuid4()},
        {"run_id": uuid4()},
    ],
)
def test_review_schema_rejects_invalid_values(pg_engine, overrides):
    with pg_engine.begin() as connection:
        ids, run_id = _seed_run(connection)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _review(connection, run_id, ids["owners"][0], **overrides)
        assert connection.scalar(text("SELECT count(*) FROM review_revisions")) == 0


def test_review_chain_rejects_wrong_owner_parent_and_branching(pg_engine):
    with pg_engine.begin() as connection:
        ids, run_id = _seed_run(connection)
        own = ids["owners"][0]
        peer_run = _run(connection, ids, _context(connection, ids))
        foreign_run = _run(
            connection, ids, _context(connection, ids, owner=1), owner_id=ids["owners"][1]
        )
        root = _review(connection, run_id, own)
        child = _review(connection, run_id, own, parent=root, number=2)
        grandchild = _review(connection, run_id, own, parent=child, number=3, decisions=[])
        peer_root = _review(connection, peer_run, own)
        foreign_root = _review(connection, foreign_run, ids["owners"][1])
        unused_run = _run(connection, ids, _context(connection, ids))
        with pytest.raises(IntegrityError) as wrong_owner, connection.begin_nested():
            _review(connection, unused_run, ids["owners"][1])
        assert wrong_owner.value.orig.sqlstate == "23503"
        for overrides in (
            {"parent_revision_id": peer_root, "revision_number": 4},
            {"parent_revision_id": foreign_root, "revision_number": 4},
            {"parent_revision_id": uuid4(), "revision_number": 4},
            {"parent_revision_id": root, "revision_number": 4},
            {"parent_revision_id": grandchild, "revision_number": 3},
            {"parent_revision_id": grandchild, "revision_number": 1},
            {},
        ):
            with pytest.raises(IntegrityError), connection.begin_nested():
                _review(connection, run_id, own, **overrides)
        self_id = uuid4()
        with pytest.raises(IntegrityError), connection.begin_nested():
            _review(connection, run_id, own, id=self_id, parent=self_id, number=4)
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text("UPDATE review_revisions SET decisions=NULL WHERE id=:id"), {"id": root}
            )
        rows = (
            connection.execute(
                text("SELECT * FROM review_revisions WHERE run_id=:id ORDER BY revision_number"),
                {"id": run_id},
            )
            .mappings()
            .all()
        )
        assert [row["id"] for row in rows] == [root, child, grandchild]
        assert [row["parent_revision_id"] for row in rows] == [None, root, child]
        assert [row["decisions"] for row in rows] == [DECISIONS, DECISIONS, []]
        assert all(row["created_at"].utcoffset() is not None for row in rows)
        for table, row_id in (
            ("review_revisions", root),
            ("review_revisions", child),
            ("analysis_runs", run_id),
            ("users", own),
        ):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text(f"DELETE FROM {table} WHERE id=:id"), {"id": row_id})
