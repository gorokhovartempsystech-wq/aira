"""B3B publication cut points, bounded reaping and metadata-only heartbeats."""

import subprocess
import sys
from dataclasses import replace
from importlib import import_module

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.test_docx_analysis_lifecycle import api, body, claim, row_count
from tests.acceptance.test_docx_analysis_runs_start import reject, start
from tests.acceptance.test_docx_analysis_runs_start import world as world


@pytest.mark.parametrize("race", ["cancel", "deadline", "source"])
def test_final_publication_gate_rechecks_after_unlocked_validation(world, monkeypatch, race):
    implementation = import_module("ara.docx_analysis_runs._lifecycle")
    c = claim(world)
    raw = body(c)
    original = implementation.capture_result
    w = world["scopes"]["own"]

    def validated(*args, **kwargs):
        result = original(*args, **kwargs)
        if race == "cancel":
            api().cancel_run(w["runtime"], document_id=w["doc"], run_id=c.run_id)
        elif race == "deadline":
            monkeypatch.setattr(implementation, "clock", lambda session: c.deadline_at)
        else:
            with world["engine"].begin() as conn:
                conn.execute(
                    text("UPDATE docx_analysis_sources SET source_data=:v"), {"v": b"Damaged"}
                )
        return result

    monkeypatch.setattr(implementation, "capture_result", validated)
    ack = api().complete_attempt(world["engine"], c, reply=raw)
    assert not ack.accepted
    assert (
        ack.state.summary.status
        == {"cancel": "cancel_requested", "deadline": "timed_out", "source": "failed"}[race]
    )
    assert row_count(world, "results") == 0


@pytest.mark.parametrize("after", [False, True])
def test_unknown_publication_commit_reconciles_without_reinference(world, monkeypatch, after):
    engine = world["engine"]
    c = claim(world)
    raw = body(c)
    inserted = []
    original = engine.dialect.do_commit

    def observe(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_results"):
            inserted.append(1)

    def commit(conn):
        if inserted:
            inserted.clear()
            if after:
                original(conn)
            raise OperationalError("COMMIT", {}, RuntimeError("Synthetic private fault"))
        return original(conn)

    event.listen(engine, "before_cursor_execute", observe)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    try:
        reject("storage_unavailable", lambda: api().complete_attempt(engine, c, reply=raw), 503)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
        monkeypatch.setattr(engine.dialect, "do_commit", original)
    assert row_count(world, "results") == (1 if after else 0)
    ack = api().complete_attempt(engine, c, reply=raw)
    assert ack.accepted and ack.replayed is after and row_count(world, "results") == 1


def test_forged_claim_buffers_are_not_authoritative(world):
    c = claim(world)
    raw = body(c)
    altered = replace(
        c,
        source=replace(c.source, source_data=b"Untrusted"),
        attempt=replace(c.attempt, request_data=b"{}"),
    )
    assert api().complete_attempt(world["engine"], altered, reply=raw).accepted


def test_damage_before_completion_is_failure_and_damage_after_success_is_error(world):
    c = claim(world)
    raw = body(c)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_sources SET source_data=:v"), {"v": b"Damaged"})
    ack = api().complete_attempt(world["engine"], c, reply=raw)
    assert not ack.accepted and ack.state.error_code == "source_corrupt"
    assert row_count(world, "results") == 0


def test_completed_result_corruption_never_acknowledges_replay(world):
    c = claim(world)
    raw = body(c)
    api().complete_attempt(world["engine"], c, reply=raw)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_results SET result_data=:v"), {"v": b"{}"})
    reject("storage_error", lambda: api().complete_attempt(world["engine"], c, reply=raw), 500)
    with world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT status FROM docx_analysis_runs")) == "succeeded"
    assert row_count(world, "results") == 1


def test_source_damage_after_success_is_reported_without_rewriting_history(world):
    c = claim(world)
    raw = body(c)
    api().complete_attempt(world["engine"], c, reply=raw)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_sources SET source_data=:v"), {"v": b"Damaged"})
    reject("storage_error", lambda: api().complete_attempt(world["engine"], c, reply=raw), 500)
    with world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT status FROM docx_analysis_runs")) == "succeeded"
    assert row_count(world, "results") == 1


def test_heartbeat_and_reaper_do_not_select_buffers(world):
    c = claim(world)
    statements = []

    def observe(conn, cursor, statement, params, context, many):
        statements.append(statement.lower())

    event.listen(world["engine"], "before_cursor_execute", observe)
    try:
        api().heartbeat(world["engine"], c)
        api().reap_expired(world["engine"])
    finally:
        event.remove(world["engine"], "before_cursor_execute", observe)
    for statement in statements:
        assert not any(
            n in statement
            for n in (
                "source_data",
                "snapshot_data",
                "command_data",
                "request_data",
                "reply_data",
                "result_data",
            )
        )


def test_reaper_small_batch_does_not_starve_expired_lease_behind_live_queue(world, monkeypatch):
    from datetime import timedelta

    c = claim(world)
    other = start(world, "peer")
    with world["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_analysis_runs SET created_at=:t,deadline_at=:d WHERE id=:id"),
            {
                "t": c.claimed_at - timedelta(seconds=1),
                "d": c.claimed_at + timedelta(seconds=299),
                "id": other.summary.run_id,
            },
        )
    implementation = import_module("ara.docx_analysis_runs._lifecycle")
    monkeypatch.setattr(implementation, "clock", lambda session: c.lease_expires_at)
    reaped = api().reap_expired(world["engine"], limit=1)
    assert (
        len(reaped) == 1
        and reaped[0].summary.run_id == c.run_id
        and reaped[0].error_code == "interrupted"
    )


def test_inert_worker_module_import():
    from tests.acceptance.conftest import ROOT

    program = """
import sys
def audit(event,args):
    if event in ('socket.connect','subprocess.Popen','os.system'):
        raise AssertionError('Unexpected worker runtime')
    if event=='open' and isinstance(args[0],str) and args[0].endswith('secrets.env'):
        raise AssertionError('Unexpected configuration read')
    if event=='import' and args[0].split('.')[0] in ('aira_ml','onnxruntime','torch'):
        raise AssertionError('Unexpected model import')
sys.addaudithook(audit)
import ara.docx_analysis_runs.lifecycle
print('inert')
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT / "src",
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip() == "inert" and not result.stderr
