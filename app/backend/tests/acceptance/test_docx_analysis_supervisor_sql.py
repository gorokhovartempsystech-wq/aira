"""Frozen F2: durable launch fence, exact scoped lifecycle and private SQL pools."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_docx_analysis_runs_start import start
from test_docx_analysis_runs_start import world as world
from test_migrations import _schema_signature

from ara.documents.storage import DocumentError

TABLE = "docx_analysis_supervisor"
V10, V11 = "0010_docx_analysis_storage", "0011_docx_analysis_supervisor"
ROOT = Path(__file__).resolve().parents[2]


def ledger():
    return importlib.import_module("ara.docx_analysis_worker.supervisor.ledger")


def life():
    return importlib.import_module("ara.docx_analysis_worker.supervisor.lifecycle")


def models():
    return importlib.import_module("ara.docx_analysis_worker.supervisor.sql_models")


def owner(engine):
    a = ledger()
    binding = models().OwnerBinding(uuid4(), uuid4())
    row = a.provision_new_database(
        engine, installation_id=binding.installation_id, expected_revision=1
    )
    row = a.take_ownership(engine, owner=binding, expected_revision=row.revision)
    return binding, row


def owned_claim(world):
    own, row = owner(world["engine"])
    out = start(world)
    scope = world["scopes"]["own"]
    result = life().claim_exact(
        scope["runtime"],
        document_id=scope["doc"],
        run_id=out.summary.run_id,
        attempt_id=uuid4(),
        worker_instance_id=uuid4(),
        owner=own,
    )
    claim = result.claim
    binding = models().LaunchBinding(
        own,
        uuid4(),
        claim.document_id,
        claim.run_id,
        claim.attempt_id,
        claim.worker_instance_id,
        claim.claim_fence,
    )
    return claim, binding, row, scope["runtime"]


def armed(world):
    claim, binding, row, runtime = owned_claim(world)
    row = ledger().arm_launch(runtime, claim, binding=binding, expected_revision=row.revision)
    return claim, binding, row, runtime


def rejected(code, fn):
    with pytest.raises(models().SupervisorStorageError) as error:
        fn()
    assert error.value.code == code
    assert "Synthetic" not in str(error.value)


def downgrade(engine):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, V10)


def test_latest_upgrade_repeat_orm_and_clean_downgrade(empty_pg_engine, apply_migrations):
    engine = empty_pg_engine
    apply_migrations(engine, V10)
    with engine.connect() as conn:
        before = _schema_signature(conn)
    apply_migrations(engine, V11)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V11
        sig = _schema_signature(conn)
        assert conn.execute(text(f"SELECT slot_key,revision,phase FROM {TABLE}")).all() == [
            (1, 1, "unprovisioned")
        ]
        assert (
            conn.scalar(
                text(
                    "SELECT relpersistence FROM pg_class WHERE oid=:t::regclass".replace(
                        ":t::regclass", "CAST(:t AS regclass)"
                    )
                ),
                {"t": TABLE},
            )
            == "p"
        )
    apply_migrations(engine, V11)
    with engine.connect() as conn:
        assert _schema_signature(conn) == sig
    assert set(inspect(engine).get_columns(TABLE)[i]["name"] for i in range(11)) == {
        "slot_key",
        "revision",
        "phase",
        "installation_id",
        "owner_epoch",
        "launch_id",
        "document_id",
        "run_id",
        "attempt_id",
        "worker_instance_id",
        "claim_fence",
    }
    assert inspect(engine).get_foreign_keys(TABLE) == []
    assert (
        getattr(importlib.import_module("ara.models"), "DocxAnalysisSupervisor").__tablename__
        == TABLE
    )
    downgrade(engine)
    with engine.connect() as conn:
        assert _schema_signature(conn) == before


@pytest.mark.parametrize(
    "values",
    [
        {"slot_key": 2},
        {"revision": 0},
        {"phase": "private-sentinel"},
        {"phase": "clean"},
        {"owner_epoch": uuid4()},
        {"launch_id": uuid4()},
        {"phase": "armed"},
        {"claim_fence": 1},
    ],
)
def test_invalid_row_shapes_fail_at_commit(pg_engine, values):
    # One otherwise valid unprovisioned row is updated, so no PK masks the check.
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        names = list(values)
        conn.execute(text(f"UPDATE {TABLE} SET " + ",".join(f"{k}=:{k}" for k in names)), values)
    assert ledger().read_fence(pg_engine).phase == "unprovisioned"


def test_provision_cas_replay_and_takeover(pg_engine):
    a = ledger()
    installation, epoch = uuid4(), uuid4()
    first = a.provision_new_database(pg_engine, installation_id=installation, expected_revision=1)
    assert first.phase == "clean" and first.revision == 2
    assert (
        a.provision_new_database(pg_engine, installation_id=installation, expected_revision=1)
        == first
    )
    rejected(
        "storage_conflict",
        lambda: a.provision_new_database(pg_engine, installation_id=uuid4(), expected_revision=1),
    )
    binding = models().OwnerBinding(installation, epoch)
    owned = a.take_ownership(pg_engine, owner=binding, expected_revision=2)
    assert owned.owner_epoch == epoch and owned.revision == 3
    assert a.take_ownership(pg_engine, owner=binding, expected_revision=2) == owned
    with pytest.raises(RuntimeError, match="^Cannot downgrade a provisioned analysis supervisor$"):
        downgrade(pg_engine)
    assert a.read_fence(pg_engine) == owned


def test_missing_row_is_blocked_not_auto_initialized(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {TABLE}"))
    rejected("recovery_required", lambda: ledger().read_fence(pg_engine))
    rejected("recovery_required", lambda: owner(pg_engine))
    with pg_engine.connect() as conn:
        assert conn.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 0


def test_provision_existing_analysis_history_is_rejected(world):
    start(world)
    rejected("recovery_required", lambda: owner(world["engine"]))
    assert ledger().read_fence(world["engine"]).phase == "unprovisioned"


def test_exact_claim_replays_original_attempt_and_time(world):
    claim, binding, row, runtime = owned_claim(world)
    replay = life().claim_exact(
        runtime,
        document_id=claim.document_id,
        run_id=claim.run_id,
        attempt_id=claim.attempt_id,
        worker_instance_id=claim.worker_instance_id,
        owner=binding.owner,
    )
    assert replay.replayed and replay.claim == claim
    with world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_analysis_attempts")) == 1
    assert ledger().read_fence(world["engine"]) == row


def test_claim_does_not_scan_other_scopes(world):
    own, _ = owner(world["engine"])
    foreign = start(world, "foreign")
    runtime = world["scopes"]["own"]["runtime"]
    with pytest.raises(DocumentError) as error:
        life().claim_exact(
            runtime,
            document_id=foreign.summary.document_id,
            run_id=foreign.summary.run_id,
            attempt_id=uuid4(),
            worker_instance_id=uuid4(),
            owner=own,
        )
    assert error.value.code == "not_found"
    with world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_analysis_attempts")) == 0


def test_concurrent_claims_one_bound_attempt(world):
    own, _ = owner(world["engine"])
    out = start(world)
    runtime = world["scopes"]["own"]["runtime"]

    def claim():
        try:
            return (
                life()
                .claim_exact(
                    runtime,
                    document_id=out.summary.document_id,
                    run_id=out.summary.run_id,
                    attempt_id=uuid4(),
                    worker_instance_id=uuid4(),
                    owner=own,
                )
                .claim
            )
        except models().SupervisorStorageError as error:
            assert error.code == "storage_conflict"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = [f.result(timeout=10) for f in [pool.submit(claim), pool.submit(claim)]]
    assert sum(v is not None for v in values) == 1


def test_armed_fence_survives_sql_cancel_and_denies_takeover(world):
    claim, binding, row, runtime = armed(world)
    old = importlib.import_module("ara.docx_analysis_runs.lifecycle")
    old.cancel_run(runtime, document_id=claim.document_id, run_id=claim.run_id)
    old.acknowledge_cancel(world["engine"], claim)
    assert ledger().read_fence(world["engine"]) == row
    rejected(
        "recovery_required",
        lambda: ledger().take_ownership(
            world["engine"],
            owner=replace(binding.owner, owner_epoch=uuid4()),
            expected_revision=row.revision,
        ),
    )
    assert ledger().read_fence(world["engine"]) == row


def test_heartbeat_receipt_uses_same_transaction_clock_and_read_does_not_extend(world):
    claim, binding, _, runtime = armed(world)
    ack = life().heartbeat(runtime, claim, owner=binding.owner, stage="analyzing")
    assert ack.accepted
    assert 0 < (ack.state.lease_expires_at - ack.heartbeat_at).total_seconds() <= 15
    with world["engine"].connect() as conn:
        stored = conn.execute(
            text("SELECT heartbeat_at,lease_expires_at FROM docx_analysis_runs")
        ).one()
    assert stored == (ack.heartbeat_at, ack.state.lease_expires_at)
    read = life().read_heartbeat(runtime, claim, owner=binding.owner)
    assert read.heartbeat_at == ack.heartbeat_at
    assert read.state.lease_expires_at == ack.state.lease_expires_at
    late = life().heartbeat(runtime, claim, owner=binding.owner, stage="loading_model")
    assert late.state.summary.stage == "analyzing"


def test_expired_heartbeat_does_not_revive(world, monkeypatch):
    claim, binding, _, runtime = armed(world)
    monkeypatch.setattr(
        life(), "clock", lambda session: claim.lease_expires_at + timedelta(microseconds=1)
    )
    ack = life().heartbeat(runtime, claim, owner=binding.owner)
    assert not ack.accepted and ack.heartbeat_at is None
    assert ack.state.summary.status == "failed"
    assert ledger().read_fence(world["engine"]).phase == "armed"


def test_drained_clear_requires_terminal_sql_and_binding(world):
    claim, binding, row, runtime = armed(world)
    a, engine = ledger(), world["engine"]
    drained = a.record_drained(engine, binding=binding, expected_revision=row.revision)
    assert drained.phase == "drained"
    assert a.record_drained(engine, binding=binding, expected_revision=row.revision) == drained
    rejected(
        "storage_conflict",
        lambda: a.clear_drained(engine, binding=binding, expected_revision=drained.revision),
    )
    old = importlib.import_module("ara.docx_analysis_runs.lifecycle")
    old.cancel_run(runtime, document_id=claim.document_id, run_id=claim.run_id)
    old.acknowledge_cancel(engine, claim)
    clean = a.clear_drained(engine, binding=binding, expected_revision=drained.revision)
    assert clean.phase == "clean" and clean.binding is None
    assert a.clear_drained(engine, binding=binding, expected_revision=drained.revision) == clean


def test_startup_snapshot_retires_only_old_queued_ids(world):
    one = start(world)
    snapshot = life().snapshot_queued(world["engine"])
    two = start(world, "peer")
    assert tuple(item.run_id for item in snapshot) == (one.summary.run_id,)
    for item in snapshot:
        state = life().retire_queued(world["engine"], item)
        assert state.summary.status == "failed" and state.error_code == "interrupted"
    with world["engine"].connect() as conn:
        assert (
            conn.scalar(
                text("SELECT status FROM docx_analysis_runs WHERE id=:id"),
                {"id": two.summary.run_id},
            )
            == "queued"
        )


def test_sql_engines_are_lazy_private_and_bounded(pg_engine):
    from ara.config import DatabaseSettings

    a = importlib.import_module("ara.docx_analysis_worker.supervisor.database")
    settings = DatabaseSettings(pg_engine.url.render_as_string(hide_password=False))
    engines = a.create_engines(settings)
    try:
        assert len({id(engines.admission), id(engines.control), id(engines.publication)}) == 3
        for engine in (engines.admission, engines.control, engines.publication):
            assert engine.pool.size() == 1
            assert engine.pool._max_overflow == 0
            a.check_database(engine)
            with engine.connect() as conn:
                for setting, expected in [
                    ("lock_timeout", "500ms"),
                    ("statement_timeout", "2s"),
                    ("idle_in_transaction_session_timeout", "2s"),
                    ("transaction_timeout", "5s"),
                    ("synchronous_commit", "on"),
                ]:
                    assert conn.exec_driver_sql("SHOW " + setting).scalar_one() == expected
        assert str(settings.database_url.get_secret_value()) not in repr(engines)
    finally:
        engines.dispose()


def test_v11_preserves_dirty_v10_history_both_directions(empty_pg_engine, apply_migrations):
    from test_docx_analysis_storage_migrations import parents, put, records

    engine = empty_pg_engine
    apply_migrations(engine, V10)
    with engine.begin() as conn:
        put(conn, records(parents(conn), "failed"))
        tables = sorted(set(inspect(conn).get_table_names()) - {"alembic_version"})
        before = {name: conn.execute(text(f'SELECT * FROM "{name}"')).all() for name in tables}
    apply_migrations(engine, V11)
    with engine.connect() as conn:
        assert {
            name: conn.execute(text(f'SELECT * FROM "{name}"')).all() for name in tables
        } == before
    downgrade(engine)
    with engine.connect() as conn:
        assert {
            name: conn.execute(text(f'SELECT * FROM "{name}"')).all() for name in tables
        } == before
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V10


def test_migration_matches_independent_normative_ddl(pg_engine):
    ddl = (ROOT / "docs/d03-17c1f2-schema.sql").read_text()
    ddl = "\n".join(line for line in ddl.splitlines() if not line.lstrip().startswith("--"))
    with pg_engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA f2_oracle")
        conn.exec_driver_sql("SET LOCAL search_path TO f2_oracle")
        for statement in ddl.split(";"):
            if statement.strip():
                conn.exec_driver_sql(statement)
        inspector = inspect(conn)
        for method in (
            inspector.get_columns,
            inspector.get_check_constraints,
            inspector.get_pk_constraint,
            inspector.get_foreign_keys,
            inspector.get_unique_constraints,
            inspector.get_indexes,
        ):

            def shape(schema):
                value = method(TABLE, schema=schema)
                if isinstance(value, list):
                    value = sorted(value, key=lambda row: row.get("name", ""))
                return str(value)

            assert shape("public") == shape("f2_oracle"), method.__name__
