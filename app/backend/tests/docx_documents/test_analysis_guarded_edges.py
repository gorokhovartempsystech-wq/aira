"""Guarded publication: SQL barriers, retry identity and late cancellation cut points."""

import copy
import pickle
import traceback
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.test_docx_analysis_guarded import api, body, claim, publisher, row_count
from tests.acceptance.test_docx_analysis_runs_start import reject
from tests.acceptance.test_docx_analysis_runs_start import world as world


def unknown(world, monkeypatch):
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
            raise OperationalError("COMMIT", {}, RuntimeError("private-sentinel"))
        return original(conn)

    event.listen(engine, "before_cursor_execute", observed)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    try:
        reject("storage_unavailable", lambda: p.complete(reply=raw), 503)
    finally:
        event.remove(engine, "before_cursor_execute", observed)
        monkeypatch.setattr(engine.dialect, "do_commit", original)
    return c, p, control, raw


def test_reconciliation_uses_real_ordered_lock_barrier(world, monkeypatch):
    c, p, control, _ = unknown(world, monkeypatch)
    engine = world["engine"]
    attempted = Event()

    def observe(conn, cursor, statement, params, context, many):
        if "docx_documents" in statement and "FOR UPDATE" in statement:
            attempted.set()

    with engine.connect() as conn:
        tx = conn.begin()
        conn.execute(
            text("SELECT id FROM docx_documents WHERE id=:id FOR UPDATE"), {"id": c.document_id}
        )
        event.listen(engine, "before_cursor_execute", observe)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(p.reconcile)
                try:
                    assert attempted.wait(5)
                    assert not future.done()
                    assert control.view().phase == "unknown"
                finally:
                    tx.rollback()
                assert not future.result(timeout=10).accepted
        finally:
            if tx.is_active:
                tx.rollback()
            event.remove(engine, "before_cursor_execute", observe)
    assert control.view().phase == "open"


def test_late_stop_during_rollback_settlement_is_durably_fenced(world, monkeypatch):
    _, p, control, _ = unknown(world, monkeypatch)
    original = p._port.settle

    def settled(permit, *, outcome):
        if outcome == "rolled_back":
            control.request_stop(now_ns=0)
        return original(permit, outcome=outcome)

    monkeypatch.setattr(p._port, "settle", settled)
    out = p.reconcile()
    assert out.state.summary.status == "cancel_requested"
    assert control.view().phase == "stopped"
    assert row_count(world, "results") == 0


def test_late_cancel_storage_failure_retains_intent_for_next_reconcile(world, monkeypatch):
    _, p, control, _ = unknown(world, monkeypatch)
    original = p._port.settle
    settled_stop = []

    def settled(permit, *, outcome):
        if outcome == "rolled_back":
            control.request_stop(now_ns=0)
            settled_stop.append(True)
        return original(permit, outcome=outcome)

    def fail(conn, cursor, statement, params, context, many):
        if settled_stop and statement.startswith("UPDATE docx_analysis_runs"):
            raise OperationalError(statement, {}, RuntimeError("private-sentinel"))

    monkeypatch.setattr(p._port, "settle", settled)
    event.listen(world["engine"], "before_cursor_execute", fail)
    try:
        reject("storage_unavailable", p.reconcile, 503)
    finally:
        event.remove(world["engine"], "before_cursor_execute", fail)
    assert control.view().phase == "stopped"
    assert p.reconcile().state.summary.status == "cancel_requested"
    assert row_count(world, "results") == 0


def test_second_reply_does_not_replace_pending_or_success(world, monkeypatch):
    _, p, _, raw = unknown(world, monkeypatch)
    reject("publication_conflict", lambda: p.complete(reply=b"{}"), 409)
    assert p.complete(reply=raw).accepted
    reject("publication_conflict", lambda: p.complete(reply=b"{}"), 409)
    assert row_count(world, "results") == 1


def test_source_corruption_is_failed_without_a_result(world):
    c = claim(world)
    raw = body(c)
    p, _ = publisher(world, c)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_sources SET source_data=:v"), {"v": b"Damaged"})
    out = p.complete(reply=raw)
    assert not out.accepted and out.state.error_code == "source_corrupt"
    assert row_count(world, "results") == 0


def test_failure_after_flush_leaves_unknown_until_a_locked_read(world):
    c = claim(world)
    p, control = publisher(world, c)
    raw = body(c)

    def fail(conn, cursor, statement, params, context, many):
        if statement == "SET CONSTRAINTS ALL IMMEDIATE":
            raise OperationalError(statement, {}, RuntimeError("private-sentinel"))

    event.listen(world["engine"], "before_cursor_execute", fail)
    try:
        reject("storage_unavailable", lambda: p.complete(reply=raw), 503)
    finally:
        event.remove(world["engine"], "before_cursor_execute", fail)
    assert control.view().phase == "unknown"
    assert not p.reconcile().accepted
    assert control.view().phase == "open"
    assert p.complete(reply=raw).accepted


def test_sanitized_exception_traceback_does_not_expose_database_fault_details(world):
    from ara.documents.storage import DocumentError

    c = claim(world)
    p, _ = publisher(world, c)
    raw = body(c)

    def fail(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_results"):
            raise OperationalError(statement, {"private": "private-sentinel"}, RuntimeError())

    event.listen(world["engine"], "before_cursor_execute", fail)
    try:
        with pytest.raises(DocumentError) as caught:
            p.complete(reply=raw)
    finally:
        event.remove(world["engine"], "before_cursor_execute", fail)
    assert "private-sentinel" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("operation", [copy.copy, copy.deepcopy, pickle.dumps])
def test_publisher_is_process_local_and_not_clonable(world, operation):
    p, _ = publisher(world, claim(world))
    with pytest.raises(TypeError):
        operation(p)


def test_constructor_does_not_call_clock_or_access_database(world, monkeypatch):
    c = claim(world)
    _, control = publisher(world, c)

    def forbidden(*args, **kwargs):
        pytest.fail("constructor runtime I/O")

    port = api().DirectPublicationPort(control, clock=forbidden)
    monkeypatch.setattr(world["engine"], "connect", forbidden)
    assert "GuardedPublisher" in repr(api().GuardedPublisher(world["engine"], c, port=port))


@pytest.mark.parametrize("field", ["run_id", "document_id"])
def test_claim_locator_mutation_after_constructor_is_rejected(world, field):
    c = claim(world)
    raw = body(c)
    p, _ = publisher(world, c)
    object.__setattr__(c, field, uuid4())
    reject("validation_error", lambda: p.complete(reply=raw), 422)
    assert row_count(world, "results") == 0


def test_real_codec_validation_does_not_hold_document_row_lock(world, monkeypatch):
    c = claim(world)
    p, _ = publisher(world, c)
    raw = body(c)
    implementation = import_module("ara.docx_analysis_runs.guarded_publish")
    original = implementation.capture_result

    def capture(*args, **kwargs):
        with world["engine"].begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout='100ms'"))
            conn.execute(
                text("SELECT id FROM docx_documents WHERE id=:id FOR UPDATE"), {"id": c.document_id}
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(implementation, "capture_result", capture)
    assert p.complete(reply=raw).accepted
