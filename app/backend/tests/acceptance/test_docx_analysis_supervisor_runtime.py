"""F3 independent portable admission, terminal and publication composition."""

import copy
import importlib
import pickle
import time
from dataclasses import replace
from threading import Event, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_docx_analysis_runs_start import world as world
from test_docx_analysis_storage_codec import execution
from test_docx_review_v1 import canonical, reply

from ara.config import DatabaseSettings
from ara.docx_analysis.storage_codec import RetryCheckCommand
from ara.docx_analysis.visible_main import build_visible_snapshot
from ara.docx_analysis_worker.supervisor import ledger, lifecycle
from ara.docx_analysis_worker.supervisor.sql_models import SupervisorStorageError


def api():
    return importlib.import_module("ara.docx_analysis_worker.supervisor.runtime")


def wait_for(fn, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        Event().wait(0.005)
    raise AssertionError("F3 observable transition did not complete")


class Clock:
    def __init__(self):
        self.offset, self.error = 0, False
        self.lock = Lock()

    def __call__(self):
        with self.lock:
            if self.error:
                raise RuntimeError("private clock diagnostic")
            return time.monotonic_ns() + self.offset

    def advance(self, ns):
        with self.lock:
            self.offset += ns


class FixturePlatform:
    """Explicit synthetic compute; never evidence of a native process exit."""

    def __init__(self, raw):
        self.clock = Clock()
        self.raw = raw
        self.done, self.cleaned = Event(), Event()
        self.done.set()
        self.cleaned.set()
        self.entered, self.stopped = Event(), Event()
        self.launch_gate = Event()
        self.launch_gate.set()
        self.trace, self.launches, self.releases = [], 0, 0
        self.renew_result, self.release_result = True, True
        self.current_slot = None
        self.closed = False

    def acquire_owner(self, root):
        self.trace.append("owner")
        return object()

    def reserve_slot(self, owner):
        assert self.current_slot is None
        self.trace.append("slot")
        self.current_slot = object()
        return self.current_slot

    def launch(self, slot, identity, budget, *, request, execution_spec):
        assert slot is self.current_slot and request and execution_spec
        self.launches += 1
        self.trace.append("launch")
        self.entered.set()
        assert self.launch_gate.wait(10)
        return SimpleNamespace(identity=identity, budget=budget, captured=False, closed=False)

    def observe(self, attempt):
        m = importlib.import_module("ara.docx_analysis_worker.supervisor.platform")
        candidate = self.raw if self.done.is_set() and not self.stopped.is_set() else None
        if candidate is not None:
            assert not attempt.closed
            attempt.captured = True
            self.trace.append("capture")
        return m.NativeObservation(
            "analyzing",
            None,
            self.done.is_set(),
            candidate,
            self.clock() if candidate is not None else None,
        )

    def renew(self, attempt, bound):
        self.trace.append(("renew", bound))
        return self.renew_result

    def stop(self, attempt, reason):
        self.trace.append(("stop", reason))
        self.stopped.set()

    def close_attempt(self, attempt):
        m = importlib.import_module("ara.docx_analysis_worker.supervisor.platform")
        closed = self.done.is_set() and self.cleaned.is_set()
        if closed:
            attempt.closed = True
            self.trace.append("close")
        return m.CloseObservation(closed, self.done.is_set())

    def release_slot(self, owner, slot):
        assert slot is self.current_slot, "stale slot reused"
        self.current_slot = None
        self.releases += 1
        self.trace.append("release")
        return self.release_result

    def close_owner(self, owner):
        assert self.current_slot is None
        self.trace.append("owner_closed")
        self.closed = True


def make(world, tmp_path, *, platform=None, provision=True, installation=None):
    w = world["scopes"]["own"]
    if platform is None:
        snapshot = build_visible_snapshot(
            w["target"].data,
            document_id=w["doc"],
            storage_revision=7,
            source_sha256=w["command"].source_sha256,
        )
        platform = FixturePlatform(canonical(reply(snapshot)))
    installation = installation or uuid4()
    if provision:
        ledger.provision_new_database(
            world["engine"], installation_id=installation, expected_revision=1
        )
    s = api()._create_supervisor(
        settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
        user_id=w["runtime"].user_id,
        project_id=w["runtime"].project_id,
        installation_id=installation,
        root=tmp_path,
        execution=execution(),
        platform=platform,
    )
    return s, platform


@pytest.fixture
def rig(world, tmp_path):
    s, p = make(world, tmp_path)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        yield s, p
    finally:
        p.launch_gate.set()
        p.done.set()
        p.cleaned.set()
        p.clock.error = False
        assert s.shutdown(timeout=5), s.view()


def submit(s, world, *, key=None, provider=None):
    w = world["scopes"]["own"]
    return s.admit_saved(
        client_request_id=key or uuid4(),
        command=w["command"],
        target_provider=provider or (lambda: w["target"]),
    )


def finished(s, ticket):
    return wait_for(lambda: v if (v := s.ticket_view(ticket)).phase == "finished" else None)


def sql_status(world):
    with world["engine"].connect() as c:
        return c.execute(text("SELECT status,error_code,fence FROM docx_analysis_runs")).all()


def test_inert_constructor_and_safe_views_A01(world, tmp_path, monkeypatch):
    s, p = make(world, tmp_path)
    assert s.view().phase == "new" and p.trace == []
    assert s.view().fixture is True
    assert "postgresql" not in repr(s)
    for method in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            method(s)
    assert s.shutdown(timeout=0)


def test_success_replay_and_capture_before_close_A06_B02_C01_D15(rig, world):
    s, p = rig
    key = uuid4()
    ticket = submit(s, world, key=key)
    result = finished(s, ticket)
    assert result.sql_state.summary.status == "succeeded"
    wait_for(lambda: s.view().phase == "ready" and s.view().active_run_id is None)
    again = submit(s, world, key=key, provider=lambda: pytest.fail("replay provider"))
    assert finished(s, again).run_id == result.run_id
    assert p.launches == 1 and p.trace.index("capture") < p.trace.index("close")
    with world["engine"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM docx_analysis_results")) == 1
    assert ledger.read_fence(world["engine"]).phase == "clean"


def test_registered_same_ticket_and_mismatch_B02_B03(rig, world):
    s, p = rig
    p.done.clear()
    key = uuid4()
    t = submit(s, world, key=key)
    assert p.entered.wait(8)
    assert submit(s, world, key=key) is t
    with pytest.raises(Exception) as caught:
        s.admit_saved(
            client_request_id=key,
            command=replace(world["scopes"]["own"]["command"], session_revision=1),
            target_provider=lambda: pytest.fail("mismatch provider"),
        )
    assert caught.value.code == "idempotency_conflict"
    with pytest.raises(api().SupervisorError):
        s.stop(object())
    for f in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            f(t)
    s.stop(t)
    p.done.set()
    assert finished(s, t).sql_state.summary.status == "cancelled"


@pytest.mark.parametrize(
    "reason,advance,status,code",
    [
        ("user", 0, "cancelled", "cancelled"),
        ("deadline", 301_000_000_000, "timed_out", "deadline_exceeded"),
        ("lease", 16_000_000_000, "failed", "interrupted"),
        ("clock", -10_000_000_000, "failed", "interrupted"),
    ],
)
def test_live_stop_reasons_and_physical_separation_A07_D02_D03_E02(
    rig, world, reason, advance, status, code
):
    s, p = rig
    p.done.clear()
    p.cleaned.clear()
    t = submit(s, world)
    assert p.entered.wait(8)
    if advance:
        p.clock.advance(advance)
    else:
        s.stop(t)
    assert p.stopped.wait(5)
    v = finished(s, t)
    assert (v.sql_state.summary.status, v.sql_state.error_code) == (status, code)
    assert ledger.read_fence(world["engine"]).phase == "armed"
    assert p.launches == 1
    p.done.set()
    p.cleaned.set()
    wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")


@pytest.mark.parametrize("deadline", [False, True])
def test_stop_while_provider_blocked_B05_D01_E11(rig, world, deadline):
    s, p = rig
    entered, release = Event(), Event()

    def provider():
        entered.set()
        assert release.wait(8)
        return world["scopes"]["own"]["target"]

    t = submit(s, world, provider=provider)
    try:
        assert entered.wait(5)
        if deadline:
            p.clock.advance(301_000_000_000)
        else:
            start = time.monotonic()
            assert s.stop(t).stop_requested
            assert time.monotonic() - start < 0.3
        assert s.view().pending_lanes
        with pytest.raises(api().SupervisorError) as caught:
            submit(s, world)
        assert caught.value.code == "busy"
    finally:
        release.set()
    out = finished(s, t)
    assert out.sql_state.summary.status == ("timed_out" if deadline else "cancelled")
    assert p.launches == 0
    assert sql_status(world)[0].fence == 1


def test_candidate_without_own_io_does_not_publish_E01(rig, world):
    s, p = rig
    p.cleaned.clear()
    t = submit(s, world)
    assert p.entered.wait(8)
    wait_for(lambda: "capture" in p.trace)
    with world["engine"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM docx_analysis_results")) == 0
    assert ledger.read_fence(world["engine"]).phase == "armed"
    p.cleaned.set()
    assert finished(s, t).sql_state.summary.status == "succeeded"


@pytest.mark.parametrize("after", [False, True])
def test_enqueue_commit_outcome_B06_B07(rig, world, monkeypatch, after):
    s, p = rig
    engine = s._engines.admission
    original = engine.dialect.do_commit
    hit = Event()

    def inserted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_runs"):
            hit.set()

    def commit(conn):
        if hit.is_set():
            hit.clear()
            if after:
                original(conn)
            raise OperationalError("COMMIT", {}, RuntimeError("private diagnostic"))
        return original(conn)

    event.listen(engine, "before_cursor_execute", inserted)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    t = submit(s, world)
    v = wait_for(
        lambda: v if (v := s.ticket_view(t)).phase in ("finished", "not_admitted") else None
    )
    assert p.launches == 0
    assert v.phase == ("finished" if after else "not_admitted")
    assert len(sql_status(world)) == int(after)
    assert "private diagnostic" not in repr(v)


@pytest.mark.parametrize("method", ["claim_exact", "arm_launch"])
@pytest.mark.parametrize("after", [False, True])
def test_claim_arm_unknown_never_relaunch_C02_C03(rig, world, monkeypatch, method, after):
    s, p = rig
    module = lifecycle if method == "claim_exact" else ledger
    original = getattr(module, method)
    hit = []

    def fault(*a, **k):
        if not hit:
            hit.append(True)
            if after:
                original(*a, **k)
            raise SupervisorStorageError("storage_unavailable")
        return original(*a, **k)

    monkeypatch.setattr(module, method, fault)
    t = submit(s, world)
    assert finished(s, t).sql_state.summary.status == "failed"
    assert p.launches == 0
    wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")


@pytest.mark.parametrize("after", [False, True])
def test_publication_commit_uncertainty_D04_D05_D06(rig, world, monkeypatch, after):
    s, p = rig
    engine = s._engines.publication
    original = engine.dialect.do_commit
    hit = Event()

    def inserted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_results"):
            hit.set()

    def commit(conn):
        if hit.is_set():
            hit.clear()
            if after:
                original(conn)
            raise OperationalError("COMMIT", {}, RuntimeError("private result diagnostic"))
        return original(conn)

    event.listen(engine, "before_cursor_execute", inserted)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    t = submit(s, world)
    v = finished(s, t)
    assert v.sql_state.summary.status == ("succeeded" if after else "failed")
    assert p.launches == 1
    wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")


@pytest.mark.parametrize("operation", ["record_drained", "clear_drained"])
def test_drain_clear_ack_loss_E03_E05(rig, world, monkeypatch, operation):
    s, p = rig
    original = getattr(ledger, operation)
    hit = []

    def fault(*a, **k):
        out = original(*a, **k)
        if not hit:
            hit.append(True)
            raise SupervisorStorageError("storage_unavailable")
        return out

    monkeypatch.setattr(ledger, operation, fault)
    t = submit(s, world)
    finished(s, t)
    wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")
    assert p.launches == 1
    assert p.releases == 2  # startup probe and own attempt, never stale lease replay


def test_invalid_result_is_not_synthetic_success_D16(rig, world):
    s, p = rig
    p.raw = b"fixture-response"
    v = finished(s, submit(s, world))
    assert (v.sql_state.summary.status, v.sql_state.error_code) == ("failed", "invalid_result")
    wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")


def test_stop_before_reserve_and_retry_B01_D04(rig, world, monkeypatch):
    s, p = rig
    module = importlib.import_module("ara.docx_analysis_runs.guarded_publish")
    original = module.capture_result
    entered, release = Event(), Event()

    def capture(*a, **k):
        entered.set()
        assert release.wait(8)
        return original(*a, **k)

    monkeypatch.setattr(module, "capture_result", capture)
    t = submit(s, world)
    try:
        assert entered.wait(8)
        s.stop(t)
        assert not s.shutdown(timeout=0.01)
        assert s.ticket_view(t).sql_state.summary.status != "cancelled"
    finally:
        release.set()
    assert finished(s, t).sql_state.summary.status in ("cancelled", "failed")


def test_shutdown_finished_threads_E12(rig, world):
    s, p = rig
    finished(s, submit(s, world))
    assert s.shutdown(timeout=5)
    assert s.view().phase == "closed" and p.closed
    assert s.shutdown(timeout=0)
    assert all(not t.is_alive() for t in s._threads())


def test_retry_new_run_same_saved_source_B01(rig, world):
    s, p = rig
    first = finished(s, submit(s, world))
    wait_for(lambda: s.view().active_run_id is None)
    t = s.retry(
        client_request_id=uuid4(), command=RetryCheckCommand(first.document_id, first.run_id)
    )
    second = finished(s, t)
    assert second.run_id != first.run_id
    assert second.sql_state.summary.status == "succeeded" and p.launches == 2


def test_queue_limit_and_metadata_retention_A05_B04(rig, world):
    from test_docx_storage_migrations import insert_row

    s, p = rig
    w = world["scopes"]["own"]
    p.done.clear()
    first = submit(s, world)
    assert p.entered.wait(8)
    tickets = []
    for _ in range(16):
        doc = uuid4()
        with world["engine"].begin() as c:
            insert_row(
                c,
                w["runtime"].project_id,
                id=doc,
                storage_revision=7,
                current_data=w["target"].data,
                current_sha256=w["command"].source_sha256,
            )
        command = replace(w["command"], document_id=doc)
        target = replace(w["target"], document_id=doc)
        ticket = s.admit_saved(
            client_request_id=uuid4(), command=command, target_provider=lambda value=target: value
        )
        tickets.append(ticket)
        wait_for(lambda: s.ticket_view(ticket).phase == "queued")
    assert s.view().queued_count == 16
    with pytest.raises(api().SupervisorError) as caught:
        submit(s, world, provider=lambda: pytest.fail("overflow provider"))
    assert caught.value.code == "queue_full"
    assert p.launches == 1
    for ticket in [first, *tickets]:
        s.stop(ticket)
    p.done.set()
    for ticket in tickets:
        assert finished(s, ticket).sql_state.summary.status == "cancelled"


def test_view_does_not_run_callbacks_and_detaches_snapshots_A08(rig, world):
    s, p = rig
    p.done.clear()
    t = submit(s, world)
    assert p.entered.wait(8)
    before = len(p.trace)
    v = s.ticket_view(t)
    if v.sql_state is not None:
        object.__setattr__(v.sql_state.summary, "status", "succeeded")
    for _ in range(100):
        assert s.view().fixture
        assert s.ticket_view(t).phase == "active"
    assert s.ticket_view(t).sql_state.summary.status == "running"
    assert p.launches == 1 and len(p.trace) >= before
    s.stop(t)
    p.done.set()
    finished(s, t)


@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_source_or_corrupt_result_never_false_success_D14_D16(rig, world, corrupt):
    s, p = rig
    p.done.clear()
    t = submit(s, world)
    assert p.entered.wait(8)
    with world["engine"].begin() as c:
        if corrupt:
            c.execute(text("UPDATE docx_analysis_sources SET source_data = :raw"), {"raw": b"bad"})
        else:
            c.execute(
                text("UPDATE projects SET owner_id=:u WHERE id=:p"),
                {
                    "u": world["scopes"]["foreign"]["runtime"].user_id,
                    "p": world["scopes"]["own"]["runtime"].project_id,
                },
            )
    p.done.set()
    wait_for(lambda: s.view().phase == "blocked" or s.ticket_view(t).phase == "finished")
    assert not any(row.status == "succeeded" for row in sql_status(world))


def test_pending_commit_does_not_allow_finalizer_D05(rig, world, monkeypatch):
    s, p = rig
    engine = s._engines.publication
    original = engine.dialect.do_commit
    hit, entered, release = Event(), Event(), Event()

    def inserted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_results"):
            hit.set()

    def commit(conn):
        if hit.is_set():
            hit.clear()
            entered.set()
            assert release.wait(8)
        return original(conn)

    event.listen(engine, "before_cursor_execute", inserted)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    t = submit(s, world)
    try:
        assert entered.wait(8)
        s.stop(t)
        assert not s.shutdown(timeout=0.02)
        assert s.ticket_view(t).sql_state.summary.status == "running"
        assert ledger.read_fence(world["engine"]).phase in ("armed", "drained")
    finally:
        release.set()
    assert finished(s, t).sql_state.summary.status == "succeeded"


def test_deadline_after_taken_rollback_is_timed_out_D07(rig, world, monkeypatch):
    s, p = rig
    engine = s._engines.publication
    original = engine.dialect.do_commit
    hit = Event()

    def inserted(conn, cursor, statement, params, context, many):
        if statement.startswith("INSERT INTO docx_analysis_results"):
            hit.set()

    def commit(conn):
        if hit.is_set():
            hit.clear()
            p.clock.advance(301_000_000_000)
            raise OperationalError("COMMIT", {}, RuntimeError("synthetic rollback"))
        return original(conn)

    event.listen(engine, "before_cursor_execute", inserted)
    monkeypatch.setattr(engine.dialect, "do_commit", commit)
    v = finished(s, submit(s, world))
    assert v.sql_state.summary.status == "timed_out"
    assert v.sql_state.error_code == "deadline_exceeded"


def test_terminal_ack_loss_keeps_same_authority_D13(rig, world, monkeypatch):
    s, p = rig
    p.done.clear()
    m = importlib.import_module("ara.docx_analysis_worker.supervisor._terminal")
    original = m.apply_exit
    seen = []

    def apply(engine, authority):
        seen.append(authority)
        out = original(engine, authority)
        if len(seen) == 1:
            raise SupervisorStorageError("storage_unavailable")
        return out

    monkeypatch.setattr(m, "apply_exit", apply)
    t = submit(s, world)
    assert p.entered.wait(8)
    s.stop(t)
    assert finished(s, t).sql_state.summary.status == "cancelled"
    assert len(seen) >= 2 and all(a is seen[0] for a in seen)
    p.done.set()


def test_late_heartbeat_does_not_revive_lease_C06(rig, world, monkeypatch):
    s, p = rig
    p.done.clear()
    original = lifecycle.heartbeat
    entered, release = Event(), Event()

    def heartbeat(*a, **kw):
        out = original(*a, **kw)
        entered.set()
        assert release.wait(8)
        return out

    monkeypatch.setattr(lifecycle, "heartbeat", heartbeat)
    t = submit(s, world)
    assert p.entered.wait(8)
    p.clock.advance(4_000_000_000)
    try:
        assert entered.wait(8)
        p.clock.advance(16_000_000_000)
        assert p.stopped.wait(5)
    finally:
        release.set()
    assert finished(s, t).sql_state.summary.status == "failed"
    assert not any(isinstance(x, tuple) and x[0] == "renew" for x in p.trace)
    p.done.set()


def test_unregistered_active_replay_is_not_reanchored_B09(rig, world):
    from test_docx_analysis_runs_start import start

    s, p = rig
    key = uuid4()
    start(world, client_request_id=key)
    t = submit(s, world, key=key)
    wait_for(lambda: s.view().phase == "blocked")
    assert p.launches == 0 and s.ticket_view(t).error_code == "recovery_required"


def test_failed_provider_releases_admission_and_keeps_safe_outcome_B08(rig, world):
    s, p = rig

    def bad():
        raise RuntimeError("private document diagnostic")

    t = submit(s, world, provider=bad)
    v = wait_for(lambda: v if (v := s.ticket_view(t)).phase == "not_admitted" else None)
    assert "private document" not in repr(v)
    assert p.launches == 0
    assert finished(s, submit(s, world)).sql_state.summary.status == "succeeded"


def test_claim_ack_after_original_deadline_never_starts_C05(rig, world, monkeypatch):
    s, p = rig
    original = lifecycle.claim_exact

    def delayed(*a, **k):
        out = original(*a, **k)
        p.clock.advance(301_000_000_000)
        return out

    monkeypatch.setattr(lifecycle, "claim_exact", delayed)
    v = finished(s, submit(s, world))
    assert v.sql_state.summary.status == "timed_out" and p.launches == 0


def test_natural_completion_during_native_renew_C08(rig, world, monkeypatch):
    s, p = rig
    p.done.clear()
    original = p.renew

    def renew(attempt, bound):
        original(attempt, bound)
        p.done.set()
        return False

    monkeypatch.setattr(p, "renew", renew)
    t = submit(s, world)
    assert p.entered.wait(8)
    p.clock.advance(4_000_000_000)
    assert finished(s, t).sql_state.summary.status == "succeeded"
