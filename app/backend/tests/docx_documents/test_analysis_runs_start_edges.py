"""B3A deadline/rollback, commit uncertainty and a real editor target integration."""

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.test_docx_analysis_runs_start import (
    api,
    counts,
    finish,
    reject,
    start,
)
from tests.acceptance.test_docx_analysis_runs_start import (
    world as world,
)
from tests.acceptance.test_docx_analysis_storage_codec import execution


@pytest.mark.parametrize("cut", [1, 2])
def test_deadline_before_or_after_flush_rolls_back_every_new_record(world, monkeypatch, cut):
    from ara.docx_analysis_runs import _storage

    t = datetime(2026, 11, 1, tzinfo=timezone.utc)
    calls = []

    def clock(session):
        calls.append(1)
        return t + timedelta(seconds=301 if len(calls) > cut else 0)

    monkeypatch.setattr(_storage, "clock", clock)
    reject("analysis_deadline_exceeded", lambda: start(world), 408)
    assert counts(world) == (0, 0)


def test_clock_going_backwards_does_not_create_a_new_budget(world, monkeypatch):
    from ara.docx_analysis_runs import _storage

    t = datetime(2026, 11, 1, tzinfo=timezone.utc)
    values = iter((t, t - timedelta(seconds=1)))
    monkeypatch.setattr(_storage, "clock", lambda session: next(values))
    reject("analysis_clock_error", lambda: start(world), 503)
    assert counts(world) == (0, 0)


@pytest.mark.parametrize("after", [False, True])
def test_lost_commit_ack_reconciles_without_repeating_provider(world, monkeypatch, after):
    engine = world["engine"]
    key = uuid4()
    inserted = []
    calls = []
    original = engine.dialect.do_commit

    def observe(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_runs"):
            inserted.append(1)

    def commit(conn):
        if inserted:
            inserted.clear()
            if after:
                original(conn)
            raise OperationalError("COMMIT", {}, RuntimeError("Synthetic private fault"))
        return original(conn)

    def provider():
        calls.append(1)
        return world["scopes"]["own"]["target"]

    event.listen(engine, "before_cursor_execute", observe)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    try:
        reject(
            "storage_unavailable",
            lambda: start(world, client_request_id=key, target_provider=provider),
            503,
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe)
        monkeypatch.setattr(engine.dialect, "do_commit", original)
    assert counts(world) == ((1, 1) if after else (0, 0))
    recovered = start(
        world,
        client_request_id=key,
        target_provider=None if after else provider,
        execution=None if after else execution(),
    )
    assert recovered.replayed is after
    assert len(calls) == (1 if after else 2) and counts(world) == (1, 1)


def test_retry_uses_parent_bytes_even_after_new_current_and_pack(world):
    from ara.docx_analysis.storage_codec import RetryCheckCommand

    w = world["scopes"]["own"]
    first = start(world)
    finish(world, first.summary.run_id)
    with world["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_documents SET current_data=:v,storage_revision=8 WHERE id=:id"),
            {"v": b"Unrelated current", "id": w["doc"]},
        )
    out = api().retry_run(
        w["runtime"],
        client_request_id=uuid4(),
        command=RetryCheckCommand(w["doc"], first.summary.run_id),
        execution=execution(model_sha256="3" * 64),
    )
    source = api().get_source(w["runtime"], document_id=w["doc"], run_id=out.summary.run_id)
    assert source.source_data == w["target"].data and source.storage_revision == 7
    assert source.execution_spec_sha256 != first.summary.execution_spec_sha256


def test_history_counter_exhaustion_and_invalid_limits_do_not_enqueue(world):
    from ara.docx_analysis.storage_codec import CodecLimits

    w = world["scopes"]["own"]
    first = start(world)
    finish(world, first.summary.run_id)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_runs SET accepted_order=:v"), {"v": 2**63 - 1})
    reject("analysis_history_exhausted", lambda: start(world), 409)
    reject(
        "analysis_limit_exceeded",
        lambda: api().get_source(
            w["runtime"],
            document_id=w["doc"],
            run_id=first.summary.run_id,
            limits=CodecLimits(max_source_bytes=1),
        ),
        413,
    )
    assert counts(world) == (1, 1)


def test_real_registry_saved_target_can_admit_exact_document(world):
    from ara.docx_analysis.storage_codec import SavedCheckCommand
    from ara.docx_documents import get_docx
    from ara.docx_editor import EditorRegistry
    from tests.acceptance.test_docx_editor_controls import control
    from tests.acceptance.test_docx_editor_registry import opening
    from tests.acceptance.test_docx_editor_save import saved_target

    w = world["scopes"]["own"]
    registry = EditorRegistry(w["runtime"])
    item = get_docx(w["runtime"], document_id=w["doc"])
    view = registry.open(**opening(registry, item)).view
    saved = registry.save(**control(view))
    target = saved_target(registry, saved)
    command = SavedCheckCommand(
        target.document_id,
        target.registry_id,
        target.session_id,
        target.command_id,
        target.command_sequence,
        target.session_revision,
        target.storage_revision,
        target.sha256,
    )
    out = api().start_saved(
        w["runtime"],
        client_request_id=uuid4(),
        command=command,
        target_provider=lambda: saved_target(registry, saved),
        execution=execution(),
    )
    source = api().get_source(w["runtime"], document_id=w["doc"], run_id=out.summary.run_id)
    assert source.source_data == target.data


def test_fresh_import_is_inert():
    from tests.acceptance.conftest import ROOT

    code = """
import sys
def audit(event,args):
    if event in ('socket.connect','subprocess.Popen','os.system'):
        raise AssertionError('Unexpected runtime I/O')
    if event=='open' and isinstance(args[0],str) and args[0].endswith('secrets.env'):
        raise AssertionError('Unexpected configuration read')
sys.addaudithook(audit)
import ara.docx_analysis_runs
print('inert')
"""
    p = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT / "src",
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert p.stdout.strip() == "inert" and not p.stderr
