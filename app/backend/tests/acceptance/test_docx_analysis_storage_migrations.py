"""Frozen B2A: exact V10 schema, commit invariants and lossless downgrade gates."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from importlib import import_module
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_docx_checkpoint_migrations import insert as checkpoint_insert
from test_docx_checkpoint_migrations import row as checkpoint_row
from test_docx_checkpoint_migrations import seed_v8
from test_docx_storage_migrations import insert_row
from test_docx_storage_transactions import bounded_connections, observe_backend, wait_for_lock
from test_migrations import _schema_signature

V9, V10 = "0009_docx_editor_checkpoints", "0010_docx_analysis_storage"
S, R, A, X = ("docx_analysis_" + n for n in ("sources", "runs", "attempts", "results"))
TABLES = (S, R, A, X)
T = datetime(2026, 11, 1, tzinfo=timezone.utc)
H = "a" * 64


def insert(conn, table, row):
    conn.execute(
        text(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join(':' + k for k in row)})"),
        row,
    )


def migrate_down(engine, target=V9):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, target)


def previous(conn):
    signature = json.loads(_schema_signature(conn))
    for name in (*TABLES, "alembic_version"):
        signature.pop(name, None)
    return signature, {
        n: conn.execute(text(f'SELECT * FROM "{n}"')).all() for n in sorted(signature)
    }


def parents(conn):
    owner, project, document = (uuid4() for _ in range(3))
    insert(conn, "users", {"id": owner})
    insert(conn, "projects", {"id": project, "owner_id": owner, "name": "Synthetic"})
    insert_row(conn, project, id=document)
    insert(conn, S, dict(document_id=document, source_sha256=H, source_data=b"Synthetic"))
    return document, project, owner


def records(scope, status="queued", claimed=False):
    document, project, owner = scope
    run, attempt = uuid4(), uuid4()
    r = dict(
        id=run,
        document_id=document,
        source_sha256=H,
        storage_revision=1,
        accepted_order=1,
        accepted_project_id=project,
        accepted_owner_id=owner,
        client_request_id=uuid4(),
        start_kind="saved",
        retry_of_run_id=None,
        command_data=b"{}",
        command_sha256=H,
        format_version=1,
        profile="docx-analysis/final-visible-main-v1",
        policy_version="docx-analysis-policy/final-visible-no-comments-v2",
        snapshot_data=b"{}",
        snapshot_sha256=H,
        execution_kind="fixture",
        execution_spec=b"{}",
        execution_spec_sha256=H,
        status=status,
        stage="preparing_document" if status == "running" else status,
        fence=0,
        attempt_id=None,
        result_sha256=None,
        error_code=None,
        created_at=T,
        deadline_at=T + timedelta(seconds=300),
        started_at=None,
        heartbeat_at=None,
        lease_expires_at=None,
        cancel_requested_at=None,
        finished_at=None,
        updated_at=T,
    )
    a = dict(
        id=attempt,
        document_id=document,
        run_id=run,
        claim_fence=1,
        worker_instance_id=uuid4(),
        request_data=b"{}",
        request_sha256=H,
        created_at=T,
    )
    x = dict(
        run_id=run,
        document_id=document,
        attempt_id=attempt,
        run_status="succeeded",
        reply_data=b"{}",
        reply_sha256=H,
        result_data=b"{}",
        result_sha256=H,
        findings_count=0,
        questions_count=0,
        no_findings=False,
        created_at=T,
    )
    claimed = claimed or status in ("running", "cancel_requested", "succeeded")
    if claimed:
        r.update(attempt_id=attempt, started_at=T, heartbeat_at=T)
    if status in ("running", "cancel_requested"):
        r.update(fence=1 if status == "running" else 2, lease_expires_at=T + timedelta(seconds=15))
    if status == "cancel_requested":
        r["cancel_requested_at"] = T
    if status in ("succeeded", "failed", "cancelled", "timed_out"):
        r.update(fence=2 if claimed else 1, finished_at=T)
        if status == "succeeded":
            r["result_sha256"] = H
        else:
            r["error_code"] = {
                "failed": "interrupted",
                "cancelled": "cancelled",
                "timed_out": "deadline_exceeded",
            }[status]
        if status == "cancelled":
            r["cancel_requested_at"] = T
        if status == "timed_out":
            r["finished_at"] = T + timedelta(seconds=300)
    return r, a, x


def put(conn, rows):
    r, a, x = rows
    insert(conn, R, r)
    if r["attempt_id"] is not None:
        insert(conn, A, a)
    if r["status"] == "succeeded":
        insert(conn, X, x)


@pytest.fixture
def world(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine, V10)
    with empty_pg_engine.begin() as conn:
        scope = parents(conn)
    return empty_pg_engine, scope


def test_exact_schema_matches_independent_frozen_ddl(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine, V10)
    pg_engine = empty_pg_engine
    ddl = (ROOT / "docs/d03-17b2-schema.sql").read_bytes()
    assert (
        sha256(ddl).hexdigest()
        == "03bc0fe9e9b596cd6ef72d415b6a6da7ea84636ff3e0ac27e7faa33a957869ee"
    )
    with pg_engine.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V10
        conn.exec_driver_sql("CREATE SCHEMA b2a_oracle")
        conn.exec_driver_sql("SET LOCAL search_path TO b2a_oracle")
        for parent in ("docx_documents", "projects", "users"):
            conn.exec_driver_sql(f"CREATE TABLE {parent} (id UUID PRIMARY KEY)")
        conn.exec_driver_sql(ddl.decode())
        inspector = inspect(conn)
        for name, cls in zip(TABLES, ("Source", "Run", "Attempt", "Result"), strict=True):

            def shape(schema):
                cols = inspector.get_columns(name, schema=schema)
                return {
                    "columns": [
                        (
                            c["name"],
                            str(c["type"]),
                            c["nullable"],
                            c["default"],
                            getattr(c["type"], "timezone", None),
                        )
                        for c in cols
                    ],
                    "pk": inspector.get_pk_constraint(name, schema=schema),
                    "unique": sorted(
                        inspector.get_unique_constraints(name, schema=schema),
                        key=lambda x: x["name"],
                    ),
                    "check": sorted(
                        inspector.get_check_constraints(name, schema=schema),
                        key=lambda x: x["name"],
                    ),
                    "indexes": sorted(
                        inspector.get_indexes(name, schema=schema), key=lambda x: x["name"]
                    ),
                    "fk": sorted(
                        (
                            {**f, "referred_schema": None}
                            for f in inspector.get_foreign_keys(name, schema=schema)
                        ),
                        key=lambda x: x["name"],
                    ),
                }

            assert shape("public") == shape("b2a_oracle"), name
            model = getattr(import_module("ara.models"), "DocxAnalysis" + cls)
            assert model.__table__ is import_module("ara.db").Base.metadata.tables[name]


@pytest.mark.parametrize("phase", ["empty", "working", "pending"])
def test_v9_upgrade_repeat_clean_downgrade_preserves_every_previous_row(
    empty_pg_engine, apply_migrations, phase
):
    apply_migrations(empty_pg_engine, "0008_docx_edit_drafts")
    document = seed_v8(empty_pg_engine)
    apply_migrations(empty_pg_engine, V9)
    with empty_pg_engine.begin() as conn:
        checkpoint_insert(conn, checkpoint_row(document, phase))
        before = previous(conn)
    apply_migrations(empty_pg_engine, V10)
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V10
        assert previous(conn) == before
        signature = _schema_signature(conn)
    apply_migrations(empty_pg_engine, V10)
    with empty_pg_engine.connect() as conn:
        assert _schema_signature(conn) == signature
    migrate_down(empty_pg_engine)
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V9
        assert previous(conn) == before
        assert not set(TABLES) & set(inspect(conn).get_table_names())
    apply_migrations(empty_pg_engine, V10)
    with empty_pg_engine.connect() as conn:
        assert previous(conn) == before
        assert all(conn.scalar(text(f"SELECT count(*) FROM {n}")) == 0 for n in TABLES)


@pytest.mark.parametrize(
    "status,claimed",
    [
        (s, False)
        for s in (
            "queued",
            "running",
            "cancel_requested",
            "succeeded",
            "failed",
            "cancelled",
            "timed_out",
        )
    ]
    + [(s, True) for s in ("failed", "cancelled", "timed_out")],
)
def test_valid_final_states_commit(world, status, claimed):
    engine, scope = world
    with engine.begin() as conn:
        put(conn, records(scope, status, claimed))
    with engine.connect() as conn:
        assert conn.scalar(text(f"SELECT status FROM {R}")) == status


@pytest.mark.parametrize(
    "case",
    [
        "missing_result",
        "wrong_digest",
        "missing_attempt",
        "orphan_attempt",
        "wrong_document",
        "result_before_success",
    ],
)
def test_partial_or_foreign_pairs_fail_at_commit(world, case):
    engine, scope = world
    rows = records(scope, "succeeded" if case in ("missing_result", "wrong_digest") else "running")
    r, a, x = rows
    with pytest.raises(IntegrityError) as caught:
        with engine.begin() as conn:
            if case == "orphan_attempt":
                r = records(scope)[0]
                a.update(run_id=r["id"])
            if case == "wrong_document":
                a["document_id"] = uuid4()
            if case == "wrong_digest":
                x["result_sha256"] = "b" * 64
            insert(conn, R, r)
            if case != "missing_attempt":
                insert(conn, A, a)
            if case in ("wrong_digest", "result_before_success"):
                insert(conn, X, x)
            # All relevant FKs are deferred: failure must occur on commit.
    assert caught.value.orig.sqlstate == "23503"


def test_success_pair_can_be_finished_after_result_insert_and_immediate_gate(world):
    engine, scope = world
    r, a, x = records(scope, "running")
    with engine.begin() as conn:
        insert(conn, R, r)
        insert(conn, A, a)
        insert(conn, X, x)
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        conn.execute(
            text(
                f"UPDATE {R} SET status='succeeded',stage='succeeded',fence=2,"
                "result_sha256=:h,finished_at=:t,lease_expires_at=NULL WHERE id=:id"
            ),
            {"h": H, "t": T, "id": r["id"]},
        )
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


RUN_INVALID = [
    {"storage_revision": 0},
    {"accepted_order": 0},
    {"format_version": 2},
    {"start_kind": "other"},
    {"retry_of_run_id": uuid4()},
    {"start_kind": "retry"},
    {"execution_kind": "real"},
    {"status": "other"},
    {"stage": "queued"},
    {"fence": 0},
    {"fence": 2},
    {"attempt_id": None},
    {"heartbeat_at": None},
    {"started_at": None},
    {"lease_expires_at": None},
    {"cancel_requested_at": T},
    {"finished_at": T},
    {"error_code": "adapter_error"},
    {"result_sha256": H},
    {"deadline_at": T + timedelta(seconds=301)},
    {"heartbeat_at": T + timedelta(seconds=300)},
    {"lease_expires_at": T},
    {"lease_expires_at": T + timedelta(seconds=16)},
    {"updated_at": "infinity"},
    {"created_at": "-infinity"},
    {"updated_at": T - timedelta(seconds=1)},
    {"profile": "A"},
    {"profile": "x" * 129},
    {"policy_version": "bad space"},
] + [
    {key: "G" * 64}
    for key in (
        "source_sha256",
        "command_sha256",
        "snapshot_sha256",
        "execution_spec_sha256",
        "result_sha256",
    )
]


@pytest.mark.parametrize("change", RUN_INVALID)
@pytest.mark.parametrize("operation", ["insert", "update"])
def test_invalid_run_shapes_rejected_before_fk(world, change, operation):
    engine, scope = world
    r, a, x = records(scope, "running")
    with engine.begin() as conn:
        if operation == "update":
            put(conn, (r, a, x))
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            if operation == "insert":
                insert(conn, R, r | change)
            else:
                conn.execute(
                    text(
                        f"UPDATE {R} SET " + ",".join(f"{k}=:{k}" for k in change) + " WHERE id=:id"
                    ),
                    change | {"id": r["id"]},
                )
        assert caught.value.orig.sqlstate == "23514"


@pytest.mark.parametrize(
    "table,column,maximum",
    [
        (S, "source_data", 33554432),
        (R, "command_data", 16384),
        (R, "snapshot_data", 33554432),
        (R, "execution_spec", 4096),
        (A, "request_data", 8388608),
        (X, "reply_data", 4194304),
        (X, "result_data", 8388608),
    ],
)
def test_byte_limits_exact_and_overflow_rolls_back(world, table, column, maximum):
    engine, scope = world
    with engine.begin() as conn:
        put(conn, records(scope, "succeeded"))
        conn.execute(text(f"UPDATE {table} SET {column}=:v"), {"v": b"x" * maximum})
        for bad in (b"", b"x" * (maximum + 1)):
            with pytest.raises(IntegrityError) as caught, conn.begin_nested():
                conn.execute(text(f"UPDATE {table} SET {column}=:v"), {"v": bad})
            assert caught.value.orig.sqlstate == "23514"
        assert conn.scalar(text(f"SELECT octet_length({column}) FROM {table}")) == maximum


@pytest.mark.parametrize("what", ["source", "queued", "failed", "running", "succeeded"])
def test_dirty_downgrade_never_discards_records(world, what):
    engine, scope = world
    with engine.begin() as conn:
        if what != "source":
            put(conn, records(scope, what))
        before = previous(conn), {n: conn.execute(text(f"SELECT * FROM {n}")).all() for n in TABLES}
        signature = _schema_signature(conn)
    with pytest.raises(RuntimeError, match="^Cannot downgrade while DOCX analysis records exist$"):
        migrate_down(engine)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V10
        assert _schema_signature(conn) == signature
        assert (
            previous(conn),
            {n: conn.execute(text(f"SELECT * FROM {n}")).all() for n in TABLES},
        ) == before


@pytest.mark.parametrize("commit", [False, True])
def test_downgrade_waits_for_source_writer_then_rechecks(empty_pg_engine, apply_migrations, commit):
    apply_migrations(empty_pg_engine, V10)
    # Seed only old entities; the new source must remain uncommitted.
    with empty_pg_engine.begin() as conn:
        scope = parents(conn)
        conn.execute(text(f"DELETE FROM {S}"))
    with bounded_connections(empty_pg_engine), ThreadPoolExecutor(max_workers=1) as pool:
        with empty_pg_engine.connect() as writer:
            tx = writer.begin()
            try:
                insert(
                    writer, S, dict(document_id=scope[0], source_sha256=H, source_data=b"Synthetic")
                )
                with observe_backend(empty_pg_engine) as (started, backend):
                    future = pool.submit(migrate_down, empty_pg_engine)
                    wait_for_lock(empty_pg_engine, started, backend)
                    (tx.commit if commit else tx.rollback)()
                    if commit:
                        with pytest.raises(RuntimeError):
                            future.result(timeout=10)
                    else:
                        future.result(timeout=10)
            finally:
                if tx.is_active:
                    tx.rollback()
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == (
            V10 if commit else V9
        )


def test_multistep_downgrade_respects_v9_dirty_checkpoint(empty_pg_engine, apply_migrations):
    apply_migrations(empty_pg_engine, "0008_docx_edit_drafts")
    doc = seed_v8(empty_pg_engine)
    apply_migrations(empty_pg_engine, V10)
    with empty_pg_engine.begin() as conn:
        checkpoint_insert(conn, checkpoint_row(doc, "working"))
        before = _schema_signature(conn), previous(conn)
    with pytest.raises(RuntimeError, match="Cannot downgrade while DOCX working checkpoints exist"):
        migrate_down(empty_pg_engine, "0008_docx_edit_drafts")
    with empty_pg_engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V10
        assert (_schema_signature(conn), previous(conn)) == before


@pytest.mark.parametrize(
    "table,change",
    [
        (S, {"source_sha256": "A" * 64}),
        (S, {"created_at": "infinity"}),
        (A, {"claim_fence": 2}),
        (A, {"request_sha256": "z" * 64}),
        (A, {"created_at": "-infinity"}),
        (X, {"reply_sha256": "bad"}),
        (X, {"result_sha256": "A" * 64}),
        (X, {"findings_count": -1}),
        (X, {"findings_count": 10001}),
        (X, {"questions_count": -1}),
        (X, {"questions_count": 10001}),
        (X, {"no_findings": True, "findings_count": 1}),
        (X, {"run_status": "failed"}),
        (X, {"created_at": "infinity"}),
    ],
)
def test_other_table_checks_on_update(world, table, change):
    engine, scope = world
    with engine.begin() as conn:
        put(conn, records(scope, "succeeded"))
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            conn.execute(
                text(f"UPDATE {table} SET " + ",".join(f"{k}=:{k}" for k in change)), change
            )
        assert caught.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("kind", ["source", "request", "order", "attempt", "result"])
def test_duplicate_identities_rejected(world, kind):
    engine, scope = world
    r, a, x = records(scope, "succeeded")
    with engine.begin() as conn:
        put(conn, (r, a, x))
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            if kind == "source":
                insert(conn, S, dict(document_id=scope[0], source_sha256=H, source_data=b"Other"))
            elif kind in ("request", "order"):
                other = records(scope, "failed")[0]
                if kind == "request":
                    other.update(client_request_id=r["client_request_id"], accepted_order=2)
                insert(conn, R, other)
            elif kind == "attempt":
                insert(conn, A, a | {"id": uuid4()})
            else:
                insert(conn, X, x)
        assert caught.value.orig.sqlstate == "23505"


@pytest.mark.parametrize("status", ["queued", "running", "cancel_requested"])
def test_active_slot_released_only_on_terminal(world, status):
    engine, scope = world
    r, a, x = records(scope, status)
    with engine.begin() as conn:
        put(conn, (r, a, x))
        other = records(scope)[0] | {"accepted_order": 2}
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            insert(conn, R, other)
        assert caught.value.orig.sqlstate == "23505"
        conn.execute(
            text(
                f"UPDATE {R} SET status='cancelled',stage='cancelled',"
                "fence=:f,lease_expires_at=NULL,finished_at=:t,cancel_requested_at=:t,"
                "error_code='cancelled' WHERE id=:id"
            ),
            {"f": 1 if status == "queued" else 2, "t": T, "id": r["id"]},
        )
        insert(conn, R, other)
        put(conn, records(parents(conn)))


def test_concurrent_active_insert_has_one_winner_and_no_loser_source(world):
    engine, scope = world
    first = records(scope)[0]
    second = records(scope)[0] | {"accepted_order": 2, "source_sha256": "b" * 64}

    def losing():
        with engine.begin() as conn:
            insert(
                conn, S, dict(document_id=scope[0], source_sha256="b" * 64, source_data=b"Second")
            )
            insert(conn, R, second)

    with bounded_connections(engine), ThreadPoolExecutor(max_workers=1) as pool:
        with engine.connect() as winner:
            tx = winner.begin()
            try:
                insert(winner, R, first)
                with observe_backend(engine) as (started, backend):
                    future = pool.submit(losing)
                    wait_for_lock(engine, started, backend)
                    tx.commit()
                    with pytest.raises(IntegrityError):
                        future.result(timeout=10)
            finally:
                if tx.is_active:
                    tx.rollback()
    with engine.connect() as conn:
        assert conn.scalar(text(f"SELECT count(*) FROM {R}")) == 1
        assert conn.scalar(text(f"SELECT count(*) FROM {S}")) == 1


def test_old_document_cannot_cascade_delete_analysis(world):
    engine, scope = world
    with engine.begin() as conn:
        put(conn, records(scope, "succeeded"))
        with pytest.raises(IntegrityError) as caught, conn.begin_nested():
            conn.execute(text("DELETE FROM docx_documents WHERE id=:id"), {"id": scope[0]})
        assert caught.value.orig.sqlstate == "23503"
