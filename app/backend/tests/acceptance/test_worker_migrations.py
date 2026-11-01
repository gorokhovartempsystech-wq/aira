"""Independent T02-03 storage constraints and reversible historical migration."""

import json
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, DateTime, Double, Integer, Text, inspect, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from test_analysis_run_migrations import ROOT, _context, _run, _seed_history

V2 = "0002_analysis_runs"
V3 = "0003_worker_execution"
OLD_TABLES = (
    "users",
    "projects",
    "documents",
    "document_versions",
    "context_revisions",
    "analysis_runs",
)
RUN_ADDITIONS = {
    "attempt_count",
    "max_attempts",
    "deadline_at",
    "available_at",
    "active_attempt_id",
    "lease_expires_at",
    "completed_at",
    "error_code",
    "result_payload",
    "incomplete_review",
}
RUN_ORIGINAL = {
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
}
ATTEMPT_COLUMNS = {
    "id",
    "run_id",
    "attempt_number",
    "project_id",
    "started_at",
    "lease_expires_at",
    "finished_at",
    "status",
    "error_code",
    "retry_delay_seconds",
    "metadata",
}
METADATA = {
    "adapter": "fixture",
    "adapter_version": "1",
    "model": None,
    "prompt_version": None,
    "model_calls": 0,
    "duration_ms": 0,
}


def _snapshot(connection):
    inspector = inspect(connection)
    return {
        table: {
            "rows": [
                dict(row)
                for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
            ],
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
        for property_name in ("columns", "foreign_keys", "unique", "checks", "indexes"):
            assert all(item in current[property_name] for item in original[property_name])
        assert current["pk"] == original["pk"]
        assert [
            {key: row[key] for key in old_row}
            for row, old_row in zip(current["rows"], original["rows"], strict=True)
        ] == original["rows"]


def _attempt(connection, ids, parent_run_id, *, number=1, **overrides):
    row = {
        "id": uuid4(),
        "run_id": parent_run_id,
        "attempt_number": number,
        "project_id": ids["projects"][0],
        "status": "running",
        "retry_delay_seconds": 1.0,
        "metadata": METADATA,
        **overrides,
    }
    columns = ", ".join(row)
    placeholders = ", ".join(
        "CAST(:metadata AS jsonb)" if name == "metadata" else f":{name}" for name in row
    )
    connection.execute(
        text(
            f"INSERT INTO analysis_attempts ({columns}, lease_expires_at) "
            f"VALUES ({placeholders}, clock_timestamp() + interval '30 seconds')"
        ),
        {**row, "metadata": json.dumps(row["metadata"])},
    )
    return row["id"]


def _update(connection, table, row_id, assignments, **parameters):
    connection.execute(
        text(f"UPDATE {table} SET {assignments} WHERE id = :row_id"),
        {"row_id": row_id, **parameters},
    )


def _seed_run(connection):
    ids = _seed_history(connection)
    context_id = _context(connection, ids)
    return ids, _run(connection, ids, context_id)


def test_worker_upgrade_repeat_and_downgrade_preserve_queued_snapshot(
    empty_pg_engine, apply_migrations
):
    apply_migrations(empty_pg_engine, V2)
    with empty_pg_engine.begin() as connection:
        _, run_id = _seed_run(connection)
        before = _snapshot(connection)
    apply_migrations(empty_pg_engine, V3)
    with empty_pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V3
        after = _snapshot(connection)
        _assert_old_preserved(before, after)
        row = (
            connection.execute(text("SELECT * FROM analysis_runs WHERE id=:id"), {"id": run_id})
            .mappings()
            .one()
        )
        assert row["attempt_count"] == 0
        assert row["available_at"].utcoffset() is not None
        assert all(row[name] is None for name in RUN_ADDITIONS - {"attempt_count", "available_at"})
        assert connection.scalar(text("SELECT count(*) FROM analysis_attempts")) == 0
    apply_migrations(empty_pg_engine, V3)
    with empty_pg_engine.connect() as connection:
        assert _snapshot(connection) == after

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_pg_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, V2)
        assert _snapshot(connection) == before
        assert set(inspect(connection).get_table_names()) == {*OLD_TABLES, "alembic_version"}
    apply_migrations(empty_pg_engine, V3)
    with empty_pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == V3
        _assert_old_preserved(before, _snapshot(connection))
        assert connection.scalar(text("SELECT id FROM analysis_runs")) == run_id


def test_worker_model_columns_indexes_and_cyclic_fk(pg_engine):
    from ara.db import Base
    from ara.models import AnalysisAttempt, AnalysisRun

    assert AnalysisAttempt.__tablename__ == "analysis_attempts"
    assert AnalysisAttempt.__table__ is Base.metadata.tables["analysis_attempts"]
    assert AnalysisRun.__table__ is Base.metadata.tables["analysis_runs"]
    inspector = inspect(pg_engine)
    runs = {column["name"]: column for column in inspector.get_columns("analysis_runs")}
    attempts = {column["name"]: column for column in inspector.get_columns("analysis_attempts")}
    assert set(runs) == RUN_ORIGINAL | RUN_ADDITIONS
    assert set(attempts) == ATTEMPT_COLUMNS
    assert {name for name, column in runs.items() if column["nullable"]} == RUN_ADDITIONS - {
        "attempt_count",
        "available_at",
    }
    assert {name for name, column in attempts.items() if column["nullable"]} == {
        "finished_at",
        "error_code",
    }
    for name in ("attempt_count", "max_attempts"):
        assert isinstance(runs[name]["type"], Integer)
    for name in ("deadline_at", "available_at", "lease_expires_at", "completed_at"):
        assert isinstance(runs[name]["type"], DateTime) and runs[name]["type"].timezone
    assert isinstance(runs["active_attempt_id"]["type"], UUID)
    assert isinstance(runs["result_payload"]["type"], JSONB)
    assert isinstance(runs["incomplete_review"]["type"], Boolean)
    assert isinstance(runs["error_code"]["type"], Text)
    assert runs["attempt_count"]["default"] is not None
    assert runs["available_at"]["default"] is not None
    for name in ("id", "run_id", "project_id"):
        assert isinstance(attempts[name]["type"], UUID)
    assert isinstance(attempts["attempt_number"]["type"], Integer)
    assert isinstance(attempts["retry_delay_seconds"]["type"], Double)
    assert isinstance(attempts["metadata"]["type"], JSONB)
    for name in ("started_at", "lease_expires_at", "finished_at"):
        assert isinstance(attempts[name]["type"], DateTime) and attempts[name]["type"].timezone
    assert attempts["started_at"]["default"] is not None
    assert inspector.get_pk_constraint("analysis_attempts")["constrained_columns"] == ["id"]
    unique = [
        constraint["column_names"]
        for constraint in inspector.get_unique_constraints("analysis_attempts")
    ]
    assert ["run_id", "attempt_number"] in unique and ["run_id", "id"] in unique
    run_indexes = [index["column_names"] for index in inspector.get_indexes("analysis_runs")]
    assert ["status", "available_at"] in run_indexes
    assert ["status", "lease_expires_at"] in run_indexes
    assert any(
        index["column_names"][0] == "run_id" for index in inspector.get_indexes("analysis_attempts")
    )
    cyclic = [
        constraint
        for constraint in AnalysisRun.__table__.foreign_key_constraints
        if list(constraint.column_keys) == ["id", "active_attempt_id"]
    ]
    assert len(cyclic) == 1 and cyclic[0].use_alter and cyclic[0].name
    for table, expected in (
        ("analysis_runs", {(("id", "active_attempt_id"), "analysis_attempts", ("run_id", "id"))}),
        (
            "analysis_attempts",
            {(("run_id",), "analysis_runs", ("id",)), (("project_id",), "projects", ("id",))},
        ),
    ):
        foreign_keys = inspector.get_foreign_keys(table)
        actual = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            for item in foreign_keys
        }
        assert expected <= actual
        assert all(
            item["options"].get("ondelete", "NO ACTION") in {"NO ACTION", "RESTRICT"}
            for item in foreign_keys
        )


@pytest.mark.parametrize(
    "assignments",
    [
        "attempt_count=-1",
        "max_attempts=0, deadline_at=clock_timestamp()",
        "max_attempts=11, deadline_at=clock_timestamp()",
        "attempt_count=1",
        "max_attempts=3",
        "deadline_at=clock_timestamp()",
        "attempt_count=4, max_attempts=3, deadline_at=clock_timestamp()",
        "status='running'",
        "lease_expires_at=clock_timestamp()",
        "completed_at=clock_timestamp()",
        "status='failed'",
        "status='succeeded'",
        "error_code='invalid_result'",
        "status='failed', completed_at=clock_timestamp()",
        "status='failed', completed_at=clock_timestamp(), error_code='adapter_error'",
        "result_payload='{}'::jsonb",
        "incomplete_review=false",
        "status='succeeded', completed_at=clock_timestamp(), result_payload='{}'::jsonb",
        "status='succeeded', completed_at=clock_timestamp(), incomplete_review=false",
        "status='succeeded', completed_at=clock_timestamp(), "
        "result_payload='null'::jsonb, incomplete_review=false",
        "status='succeeded', completed_at=clock_timestamp(), "
        "result_payload='[]'::jsonb, incomplete_review=false",
        "status='failed', completed_at=clock_timestamp(), error_code='invalid_result', "
        "result_payload='{}'::jsonb, incomplete_review=false",
    ],
)
def test_worker_run_state_rejects_inconsistent_values(pg_engine, assignments):
    with pg_engine.begin() as connection:
        _, run_id = _seed_run(connection)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _update(connection, "analysis_runs", run_id, assignments)
        assert connection.scalar(text("SELECT status FROM analysis_runs")) == "queued"


@pytest.mark.parametrize(
    "overrides",
    [
        {"attempt_number": 0},
        {"attempt_number": -1},
        {"run_id": uuid4()},
        {"project_id": uuid4()},
        {"metadata": []},
        {"metadata": None},
        {"retry_delay_seconds": -0.01},
        {"retry_delay_seconds": 300.01},
        {"retry_delay_seconds": float("nan")},
        {"retry_delay_seconds": float("inf")},
        {"status": "queued"},
        {"status": "failed"},
        {"status": "expired"},
        {"status": "succeeded"},
        {"error_code": "adapter_error"},
    ],
)
def test_attempt_schema_rejects_invalid_rows(pg_engine, overrides):
    with pg_engine.begin() as connection:
        ids, run_id = _seed_run(connection)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _attempt(connection, ids, run_id, **overrides)


def test_attempt_state_rules_and_active_attempt_belong_to_exact_run(pg_engine):
    with pg_engine.begin() as connection:
        ids, run_id = _seed_run(connection)
        other_run = _run(connection, ids, _context(connection, ids))
        attempt_id = _attempt(connection, ids, run_id)
        other_attempt = _attempt(connection, ids, other_run)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _attempt(connection, ids, run_id)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _update(
                connection,
                "analysis_runs",
                run_id,
                "active_attempt_id=:attempt",
                attempt=attempt_id,
            )
        for invalid_attempt in (other_attempt, uuid4()):
            with pytest.raises(IntegrityError), connection.begin_nested():
                _update(
                    connection,
                    "analysis_runs",
                    run_id,
                    "status='running', active_attempt_id=:attempt, "
                    "lease_expires_at=clock_timestamp()+interval '30 seconds', "
                    "attempt_count=1, max_attempts=3, "
                    "deadline_at=clock_timestamp()+interval '5 minutes'",
                    attempt=invalid_attempt,
                )
        _update(
            connection,
            "analysis_runs",
            run_id,
            "status='running', active_attempt_id=:attempt, "
            "lease_expires_at=clock_timestamp()+interval '30 seconds', "
            "attempt_count=1, max_attempts=3, deadline_at=clock_timestamp()+interval '5 minutes'",
            attempt=attempt_id,
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text("DELETE FROM analysis_attempts WHERE id=:id"), {"id": attempt_id}
            )
        for assignments in (
            "active_attempt_id=NULL",
            "lease_expires_at=NULL",
            "status='queued'",
            "result_payload='{}'::jsonb, incomplete_review=false",
        ):
            with pytest.raises(IntegrityError), connection.begin_nested():
                _update(connection, "analysis_runs", run_id, assignments)
        for assignments in (
            "finished_at=clock_timestamp()",
            "status='expired', finished_at=clock_timestamp()",
            "status='succeeded', finished_at=clock_timestamp(), error_code='adapter_error'",
            "status='failed', finished_at=clock_timestamp(), error_code='attempts_exhausted'",
        ):
            with pytest.raises(IntegrityError), connection.begin_nested():
                _update(connection, "analysis_attempts", attempt_id, assignments)
        _update(
            connection,
            "analysis_attempts",
            attempt_id,
            "status='expired', finished_at=clock_timestamp(), error_code='lease_expired'",
        )
        _update(
            connection,
            "analysis_runs",
            run_id,
            "status='queued', active_attempt_id=NULL, lease_expires_at=NULL",
        )
        for code in (
            "deadline_exceeded",
            "attempts_exhausted",
            "access_revoked",
            "invalid_request",
            "invalid_result",
        ):
            with connection.begin_nested() as savepoint:
                _update(
                    connection,
                    "analysis_runs",
                    run_id,
                    "status='failed', completed_at=clock_timestamp(), error_code=:code",
                    code=code,
                )
                savepoint.rollback()
        _update(
            connection,
            "analysis_runs",
            run_id,
            "status='succeeded', completed_at=clock_timestamp(), "
            "result_payload='{}'::jsonb, incomplete_review=false",
        )
        for assignments in ("completed_at=NULL", "result_payload=NULL", "incomplete_review=NULL"):
            with pytest.raises(IntegrityError), connection.begin_nested():
                _update(connection, "analysis_runs", run_id, assignments)
        for table, row_id in (("analysis_runs", run_id), ("projects", ids["projects"][0])):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text(f"DELETE FROM {table} WHERE id=:id"), {"id": row_id})
