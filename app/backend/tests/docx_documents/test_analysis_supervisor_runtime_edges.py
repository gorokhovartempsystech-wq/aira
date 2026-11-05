"""Supplemental behavior at natural completion and sanitized job boundaries."""

from threading import Event

from test_docx_analysis_runs_start import world as world
from test_docx_analysis_supervisor_runtime import finished, submit, wait_for
from test_docx_analysis_supervisor_runtime import rig as rig

from ara.documents.storage import DocumentError
from ara.docx_analysis_worker.supervisor import lifecycle
from ara.docx_analysis_worker.supervisor._jobs import Lane
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine


def test_natural_completion_keeps_sql_lease_through_multiple_heartbeats(rig, world, monkeypatch):
    import ara.docx_analysis_runs.guarded_publish as guarded

    s, p = rig
    entered, release = Event(), Event()
    acks = []
    original, heartbeat = guarded.capture_result, lifecycle.heartbeat

    def capture(*a, **k):
        entered.set()
        assert release.wait(8)
        return original(*a, **k)

    def renew(*a, **k):
        out = heartbeat(*a, **k)
        acks.append(out)
        return out

    monkeypatch.setattr(guarded, "capture_result", capture)
    monkeypatch.setattr(lifecycle, "heartbeat", renew)
    ticket = submit(s, world)
    try:
        assert entered.wait(8)
        for count in (1, 2):
            p.clock.advance(4_000_000_000)
            wait_for(lambda: len(acks) >= count)
        assert s.ticket_view(ticket).stop_requested is False
        assert not any(isinstance(x, tuple) and x[0] == "renew" for x in p.trace)
    finally:
        release.set()
    assert finished(s, ticket).sql_state.summary.status == "succeeded"


def test_job_does_not_export_arbitrary_exception_code():
    lane = Lane("edge", Event())
    lane.start()
    try:

        def work():
            raise DocumentError(500, "PRIVATE_DOCUMENT_TEXT", "private diagnostic", False)

        lane.submit(1, work)
        result = wait_for(lane.take)
        assert result.error == "storage_error"
        assert "PRIVATE" not in repr(result) and "diagnostic" not in repr(result)
    finally:
        lane.close()
        lane.thread.join(2)
        assert not lane.thread.is_alive()


def test_registered_replay_survives_unknown_enqueue_and_clock_fault(rig, world, monkeypatch):
    from uuid import uuid4

    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError

    from ara.docx_analysis_runs import _storage

    s, p = rig
    inserted, lookup_entered, lookup_release = Event(), Event(), Event()
    engine = s._engines.admission
    original_commit, original_lookup = engine.dialect.do_commit, _storage.lookup
    calls = []

    def saw_insert(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_runs"):
            inserted.set()

    def commit(conn):
        if inserted.is_set():
            inserted.clear()
            original_commit(conn)
            raise OperationalError("COMMIT", {}, RuntimeError("synthetic lost ACK"))
        return original_commit(conn)

    def lookup(*a, **k):
        calls.append(True)
        if len(calls) > 1:
            lookup_entered.set()
            assert lookup_release.wait(8)
        return original_lookup(*a, **k)

    event.listen(engine, "before_cursor_execute", saw_insert)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    monkeypatch.setattr(_storage, "lookup", lookup)
    key = uuid4()
    ticket = submit(s, world, key=key)
    try:
        assert lookup_entered.wait(8)
        assert s.view().phase == "blocked"
        p.clock.error = True
        assert submit(s, world, key=key) is ticket
    finally:
        p.clock.error = False
        lookup_release.set()
    assert finished(s, ticket).sql_state.summary.status == "failed"
    assert p.launches == 0
