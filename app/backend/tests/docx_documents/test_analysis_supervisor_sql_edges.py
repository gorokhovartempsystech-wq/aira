"""SQL-only crash cut points; none of these fixtures are native physical proof."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import event, text
from test_docx_analysis_runs_start import start
from test_docx_analysis_runs_start import world as world
from test_docx_analysis_supervisor_sql import (
    armed,
    ledger,
    life,
    models,
    owned_claim,
    owner,
    rejected,
)

from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine

# Fixtures are intentionally imported from independent synthetic admission tests.


def lose_write_ack(engine, monkeypatch, table):
    original = engine.dialect.do_commit
    pending, fired = [False], [False]

    def seen(conn, cursor, statement, parameters, context, many):
        normalized = statement.lower().lstrip()
        if not fired[0] and (
            normalized.startswith("insert into " + table)
            or normalized.startswith("update " + table)
        ):
            pending[0] = True

    event.listen(engine, "before_cursor_execute", seen)

    def commit(connection):
        original(connection)
        if pending[0] and not fired[0]:
            fired[0] = True
            raise psycopg.OperationalError("synthetic acknowledgement loss")

    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    return fired


def test_claim_commit_ack_loss_replays_same_original_attempt(world, monkeypatch):
    engine = world["engine"]
    own, _ = owner(engine)
    out = start(world)
    scope = world["scopes"]["own"]
    kwargs = dict(
        document_id=scope["doc"],
        run_id=out.summary.run_id,
        attempt_id=uuid4(),
        worker_instance_id=uuid4(),
        owner=own,
    )
    fired = lose_write_ack(engine, monkeypatch, "docx_analysis_attempts")
    rejected("storage_unavailable", lambda: life().claim_exact(scope["runtime"], **kwargs))
    assert fired[0]
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT started_at,lease_expires_at FROM docx_analysis_runs")
        ).one()
    result = life().claim_exact(scope["runtime"], **kwargs)
    assert result.replayed and result.claim.attempt_id == kwargs["attempt_id"]
    assert (result.claim.claimed_at, result.claim.lease_expires_at) == before
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_analysis_attempts")) == 1


def test_arm_commit_ack_loss_does_not_create_second_binding(world, monkeypatch):
    claim, binding, row, runtime = owned_claim(world)
    engine = world["engine"]
    fired = lose_write_ack(engine, monkeypatch, "docx_analysis_supervisor")
    rejected(
        "storage_unavailable",
        lambda: ledger().arm_launch(
            runtime, claim, binding=binding, expected_revision=row.revision
        ),
    )
    assert fired[0]
    stored = ledger().read_fence(engine)
    assert stored.phase == "armed" and stored.revision == row.revision + 1
    assert (
        ledger().arm_launch(runtime, claim, binding=binding, expected_revision=row.revision)
        == stored
    )


def test_clear_commit_ack_loss_retains_terminal_run_and_clean_receipt(world, monkeypatch):
    claim, binding, row, runtime = armed(world)
    engine, a = world["engine"], ledger()
    drained = a.record_drained(engine, binding=binding, expected_revision=row.revision)
    old = importlib.import_module("ara.docx_analysis_runs.lifecycle")
    old.cancel_run(runtime, document_id=claim.document_id, run_id=claim.run_id)
    old.acknowledge_cancel(engine, claim)
    fired = lose_write_ack(engine, monkeypatch, "docx_analysis_supervisor")
    rejected(
        "storage_unavailable",
        lambda: a.clear_drained(engine, binding=binding, expected_revision=drained.revision),
    )
    assert fired[0]
    clean = a.read_fence(engine)
    assert clean.phase == "clean" and clean.binding is None
    assert a.clear_drained(engine, binding=binding, expected_revision=drained.revision) == clean
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT status FROM docx_analysis_runs")) == "cancelled"


def test_competing_owners_one_cas_winner(pg_engine):
    own, row = owner(pg_engine)

    def take():
        value = replace(own, owner_epoch=uuid4())
        try:
            return ledger().take_ownership(pg_engine, owner=value, expected_revision=row.revision)
        except models().SupervisorStorageError as error:
            assert error.code == "storage_conflict"
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = [f.result(timeout=10) for f in [pool.submit(take), pool.submit(take)]]
    assert sum(value is not None for value in rows) == 1
    assert ledger().read_fence(pg_engine).revision == row.revision + 1


@pytest.mark.parametrize("expected", [True, 0, -1, 1.0, 2**63 - 1, 2**63])
def test_invalid_revision_does_not_mutate(pg_engine, expected):
    before = ledger().read_fence(pg_engine)
    rejected(
        "validation_error",
        lambda: ledger().provision_new_database(
            pg_engine, installation_id=uuid4(), expected_revision=expected
        ),
    )
    assert ledger().read_fence(pg_engine) == before


def test_foreign_worker_cannot_extend_or_arm(world):
    claim, binding, row, runtime = owned_claim(world)
    wrong = replace(claim, worker_instance_id=uuid4())
    rejected(
        "validation_error",
        lambda: ledger().arm_launch(
            runtime, wrong, binding=binding, expected_revision=row.revision
        ),
    )
    armed_row = ledger().arm_launch(runtime, claim, binding=binding, expected_revision=row.revision)
    ack = life().heartbeat(runtime, wrong, owner=binding.owner)
    assert not ack.accepted and ack.heartbeat_at is None
    assert ledger().read_fence(world["engine"]) == armed_row


def test_drained_can_be_adopted_but_armed_cannot(world):
    claim, binding, row, runtime = armed(world)
    engine, a = world["engine"], ledger()
    drained = a.record_drained(engine, binding=binding, expected_revision=row.revision)
    new_owner = replace(binding.owner, owner_epoch=uuid4())
    adopted = a.take_ownership(engine, owner=new_owner, expected_revision=drained.revision)
    assert (
        adopted.phase == "drained"
        and adopted.binding.worker_instance_id == claim.worker_instance_id
    )
    assert adopted.binding.owner == new_owner
    rejected(
        "storage_conflict",
        lambda: a.record_drained(engine, binding=binding, expected_revision=adopted.revision),
    )
    old = importlib.import_module("ara.docx_analysis_runs.lifecycle")
    old.cancel_run(runtime, document_id=claim.document_id, run_id=claim.run_id)
    old.acknowledge_cancel(engine, claim)
    clean = a.clear_drained(engine, binding=adopted.binding, expected_revision=adopted.revision)
    assert clean.owner_epoch == new_owner.owner_epoch and clean.phase == "clean"


def test_success_result_survives_drain_clear(world):
    from test_docx_analysis_lifecycle import body

    claim, binding, row, runtime = armed(world)
    old = importlib.import_module("ara.docx_analysis_runs.lifecycle")
    outcome = old.complete_attempt(world["engine"], claim, reply=body(claim))
    assert outcome.accepted
    drained = ledger().record_drained(
        world["engine"], binding=binding, expected_revision=row.revision
    )
    ledger().clear_drained(world["engine"], binding=binding, expected_revision=drained.revision)
    with world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT status FROM docx_analysis_runs")) == "succeeded"
        assert conn.scalar(text("SELECT count(*) FROM docx_analysis_results")) == 1


def test_deleted_history_cannot_remove_fence(world):
    claim, binding, row, _ = armed(world)
    # A deliberately deleted SQL history in a disposable DB must leave the independent fence.
    with world["engine"].begin() as conn:
        conn.execute(text("DELETE FROM docx_analysis_attempts"))
        conn.execute(text("DELETE FROM docx_analysis_runs"))
    assert ledger().read_fence(world["engine"]) == row
    drained = ledger().record_drained(
        world["engine"], binding=binding, expected_revision=row.revision
    )
    from ara.documents.storage import DocumentError

    with pytest.raises(DocumentError):
        ledger().clear_drained(world["engine"], binding=binding, expected_revision=drained.revision)
    assert ledger().read_fence(world["engine"]) == drained


def test_retire_rechecks_a_run_claimed_after_snapshot(world):
    own, _ = owner(world["engine"])
    out = start(world)
    snapshot = life().snapshot_queued(world["engine"])
    scope = world["scopes"]["own"]
    result = life().claim_exact(
        scope["runtime"],
        document_id=scope["doc"],
        run_id=out.summary.run_id,
        attempt_id=uuid4(),
        worker_instance_id=uuid4(),
        owner=own,
    )
    retired = life().retire_queued(world["engine"], snapshot[0])
    assert retired.summary.status == "running" and retired.attempt_id == result.claim.attempt_id


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://example.invalid/db",
        "postgresql+psycopg://192.0.2.1/db",
        "postgresql+psycopg://127.0.0.1/db?options=-csynchronous_commit%3Doff",
        "postgresql+psycopg:///db?host=127.0.0.1,127.0.0.2",
    ],
)
def test_invalid_endpoint_is_sanitized(url):
    from ara.config import DatabaseSettings

    a = importlib.import_module("ara.docx_analysis_worker.supervisor.database")
    with pytest.raises(models().SupervisorStorageError) as error:
        a.create_engines(DatabaseSettings(url))
    assert error.value.code == "validation_error"
    assert url not in str(error.value)


def test_control_pool_cannot_overflow(pg_engine):
    from sqlalchemy.exc import TimeoutError

    from ara.config import DatabaseSettings

    a = importlib.import_module("ara.docx_analysis_worker.supervisor.database")
    engines = a.create_engines(
        DatabaseSettings(pg_engine.url.render_as_string(hide_password=False))
    )
    try:
        with engines.control.connect(), pytest.raises(TimeoutError):
            engines.control.connect()
        assert engines.control.pool.checkedout() == 0
    finally:
        engines.dispose()


@pytest.mark.parametrize(
    "column,value",
    [
        ("document_id", uuid4()),
        ("snapshot_sha256", "b" * 64),
        ("command_sha256", "b" * 64),
        ("execution_spec_sha256", "b" * 64),
    ],
)
def test_claim_metadata_is_bound_before_heartbeat(world, column, value):
    claim, binding, row, runtime = armed(world)
    forged = replace(claim, source=replace(claim.source, **{column: value}))
    before = life().read_heartbeat(runtime, claim, owner=binding.owner)
    assert not life().heartbeat(runtime, forged, owner=binding.owner).accepted
    after = life().read_heartbeat(runtime, claim, owner=binding.owner)
    assert after.heartbeat_at == before.heartbeat_at
    assert after.state.lease_expires_at == before.state.lease_expires_at
    assert ledger().read_fence(world["engine"]) == row


@pytest.mark.parametrize("kind", ["duplicate", "malformed"])
def test_invalid_singleton_never_becomes_new_authority(empty_pg_engine, apply_migrations, kind):
    apply_migrations(empty_pg_engine, "0011_docx_analysis_supervisor")
    pg_engine = empty_pg_engine
    from alembic import command
    from alembic.config import Config

    from tests.acceptance.test_docx_analysis_supervisor_sql import ROOT

    with pg_engine.begin() as conn:
        if kind == "duplicate":
            conn.execute(
                text("ALTER TABLE docx_analysis_supervisor DROP CONSTRAINT ck_dasv_singleton")
            )
            conn.execute(text("INSERT INTO docx_analysis_supervisor(slot_key) VALUES(2)"))
        else:
            conn.execute(text("ALTER TABLE docx_analysis_supervisor DROP CONSTRAINT ck_dasv_shape"))
            conn.execute(text("UPDATE docx_analysis_supervisor SET launch_id=:v"), {"v": uuid4()})
    rejected("recovery_required", lambda: ledger().read_fence(pg_engine))
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    with pytest.raises(RuntimeError, match="Cannot downgrade a provisioned analysis supervisor"):
        with pg_engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0010_docx_analysis_storage")
    with pg_engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version"))
            == "0011_docx_analysis_supervisor"
        )


def test_startup_snapshot_does_not_silently_truncate_overflow(pg_engine):
    from test_docx_analysis_storage_migrations import parents, put, records

    with pg_engine.begin() as conn:
        for _ in range(17):
            put(conn, records(parents(conn)))
    rejected("queue_overflow", lambda: life().snapshot_queued(pg_engine))
    with pg_engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT count(*) FROM docx_analysis_runs WHERE status='queued'")) == 17
        )
