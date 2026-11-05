"""Frozen C1B: publication permission, durable commit and uncertain outcomes."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib import import_module
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_docx_analysis_lifecycle import api as lifecycle
from test_docx_analysis_lifecycle import body, claim, row_count
from test_docx_analysis_runs_start import reject
from test_docx_analysis_runs_start import world as world

from ara.docx_analysis_worker.control import AttemptControl, AttemptIdentity, Budget


def api():
    return import_module("ara.docx_analysis_runs.guarded")


def publisher(world, c, *, closed=True):
    control = AttemptControl(
        AttemptIdentity(c.run_id, c.attempt_id, c.worker_instance_id, 1),
        Budget(300_000_000_000, 15_000_000_000, 0, 0),
    )
    if closed:
        control.mark_child_closed(now_ns=0)
    port = api().DirectPublicationPort(control, clock=lambda: 0)
    return api().GuardedPublisher(world["engine"], c, port=port), control


def test_complete_validates_publishes_and_replays_without_new_permit(world, monkeypatch):
    c = claim(world)
    p, control = publisher(world, c)
    monkeypatch.setattr(lifecycle(), "complete_attempt", lambda *a, **k: pytest.fail("unguarded"))
    raw = body(c)
    assert p.complete(reply=raw).accepted
    assert control.view().phase == "succeeded"
    again = p.complete(reply=raw)
    assert again.accepted and again.replayed
    assert row_count(world, "results") == 1


@pytest.mark.parametrize("stop,closed", [(True, True), (False, False)])
def test_no_publication_without_open_clean_child_permission(world, stop, closed):
    c = claim(world)
    p, control = publisher(world, c, closed=closed)
    if stop:
        control.request_stop(now_ns=0)
    out = p.complete(reply=body(c))
    assert not out.accepted and out.state.summary.status == "running"
    assert row_count(world, "results") == 0


def test_stop_during_unlocked_validation_wins(world, monkeypatch):
    c = claim(world)
    p, control = publisher(world, c)
    implementation = import_module("ara.docx_analysis_runs.guarded_publish")
    original = implementation.capture_result

    def capture(*args, **kwargs):
        value = original(*args, **kwargs)
        control.request_stop(now_ns=0)
        return value

    monkeypatch.setattr(implementation, "capture_result", capture)
    assert not p.complete(reply=body(c)).accepted
    assert row_count(world, "results") == 0


def test_stop_after_reserve_does_not_erase_committed_result(world):
    c = claim(world)
    p, control = publisher(world, c)

    def inserted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_results"):
            assert control.view().phase == "committing"
            control.request_stop(now_ns=0)

    event.listen(world["engine"], "after_cursor_execute", inserted)
    try:
        assert p.complete(reply=body(c)).accepted
    finally:
        event.remove(world["engine"], "after_cursor_execute", inserted)
    assert control.view().phase == "succeeded" and control.view().stop_requested


@pytest.mark.parametrize("after,stop", [(False, False), (True, False), (False, True), (True, True)])
def test_unknown_commit_reconciles_exact_result_or_locked_absence(world, monkeypatch, after, stop):
    c = claim(world)
    p, control = publisher(world, c)
    raw = body(c)
    engine = world["engine"]
    original, inserted = engine.dialect.do_commit, []

    def observed(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_results"):
            inserted.append(True)

    def commit(conn):
        if inserted:
            inserted.clear()
            if after:
                original(conn)
            raise OperationalError("COMMIT", {}, RuntimeError("private-sentinel"))
        return original(conn)

    event.listen(engine, "before_cursor_execute", observed)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    try:
        reject("storage_unavailable", lambda: p.complete(reply=raw), 503)
    finally:
        event.remove(engine, "before_cursor_execute", observed)
        monkeypatch.setattr(engine.dialect, "do_commit", original)
    assert control.view().phase == "unknown"
    if stop:
        control.request_stop(now_ns=0)
    out = p.reconcile()
    assert row_count(world, "results") == int(after)
    if after:
        assert out.accepted and out.replayed and control.view().phase == "succeeded"
    elif stop:
        assert not out.accepted and out.state.summary.status == "cancel_requested"
        assert control.view().phase == "stopped"
        assert not p.complete(reply=raw).accepted
    else:
        assert not out.accepted and control.view().phase == "open"
        assert p.complete(reply=raw).accepted


@pytest.mark.parametrize("race", ["cancel", "deadline", "owner"])
def test_final_gate_respects_sql_cancellation_deadline_and_owner(world, monkeypatch, race):
    c = claim(world)
    p, _ = publisher(world, c)
    raw = body(c)
    if race == "cancel":
        w = world["scopes"]["own"]
        lifecycle().cancel_run(w["runtime"], document_id=c.document_id, run_id=c.run_id)
    elif race == "deadline":
        monkeypatch.setattr(
            import_module("ara.docx_analysis_runs._lifecycle"),
            "clock",
            lambda session: c.deadline_at,
        )
    else:
        with world["engine"].begin() as conn:
            conn.execute(
                text("UPDATE projects SET owner_id=:id WHERE id=:p"),
                {
                    "id": world["scopes"]["foreign"]["runtime"].user_id,
                    "p": world["scopes"]["own"]["runtime"].project_id,
                },
            )
    out = p.complete(reply=raw)
    assert not out.accepted
    assert (
        out.state.summary.status
        == {"cancel": "cancel_requested", "deadline": "timed_out", "owner": "failed"}[race]
    )
    assert row_count(world, "results") == 0


def test_foreign_port_identity_and_invalid_reply_type_rejected(world):
    c = claim(world)
    p, _ = publisher(world, c)
    reject("validation_error", lambda: p.complete(reply="private-sentinel"), 422)
    control = AttemptControl(
        AttemptIdentity(uuid4(), c.attempt_id, c.worker_instance_id, 1), Budget(100, 10, 0, 0)
    )
    reject(
        "validation_error",
        lambda: api().GuardedPublisher(
            world["engine"], c, port=api().DirectPublicationPort(control, clock=lambda: 0)
        ),
        422,
    )
    assert row_count(world, "results") == 0


def test_invalid_result_and_corrupt_source_never_create_success(world):
    c = claim(world)
    p, _ = publisher(world, c)
    out = p.complete(reply=b"{}")
    assert not out.accepted and out.state.error_code == "invalid_result"
    assert row_count(world, "results") == 0


def test_forged_claim_buffers_do_not_override_database(world):
    c = claim(world)
    altered = replace(
        c,
        source=replace(c.source, source_data=b"private-sentinel"),
        attempt=replace(c.attempt, request_data=b"{}"),
    )
    p, _ = publisher(world, altered)
    assert p.complete(reply=body(c)).accepted
    assert "private-sentinel" not in repr(p)


def test_same_publisher_is_busy_without_blocking_stop(world, monkeypatch):
    c = claim(world)
    p, control = publisher(world, c)
    raw = body(c)
    implementation = import_module("ara.docx_analysis_runs.guarded_publish")
    original = implementation.capture_result
    entered, release = Event(), Event()

    def capture(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(implementation, "capture_result", capture)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(p.complete, reply=raw)
        try:
            assert entered.wait(5)
            reject("publication_in_progress", p.reconcile, 409)
            control.request_stop(now_ns=0)
        finally:
            release.set()
        assert not future.result(timeout=10).accepted


def test_existing_success_corruption_does_not_rewrite_history(world):
    c = claim(world)
    p, _ = publisher(world, c)
    raw = body(c)
    p.complete(reply=raw)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_results SET reply_data=:v"), {"v": b"{}"})
    reject("storage_error", p.reconcile, 500)
    assert row_count(world, "results") == 1
    w = world["scopes"]["own"]
    assert (
        lifecycle()
        .read_state(w["runtime"], document_id=c.document_id, run_id=c.run_id)
        .summary.status
        == "succeeded"
    )


def test_reconcile_before_publication_is_only_a_read(world):
    c = claim(world)
    p, control = publisher(world, c)
    assert not p.reconcile().accepted
    assert control.view().phase == "open"
    assert row_count(world, "results") == 0
