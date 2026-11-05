"""Frozen F1: one dispatcher, bounded publication delivery and conservative time."""

import copy
import importlib
import pickle
import threading
import time
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from ara.documents.storage import DocumentError
from ara.docx_analysis_runs.guarded_port import PublicationPort
from ara.docx_analysis_worker.control import AttemptIdentity, Budget, CommitPermit, ControlError

S = 1_000_000_000


def api():
    return importlib.import_module("ara.docx_analysis_worker.supervisor")


class Clock:
    value = 0
    error = False

    def __call__(self):
        if self.error:
            raise RuntimeError("private-sentinel")
        return self.value


def make(*, closed=False, guard=0):
    c = Clock()
    d = api().create_dispatcher(
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
        Budget(300 * S, 15 * S, 0, guard),
        clock=c,
    )
    if closed:
        d.post_child_closed()
    d.step()
    return d, c


def until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline, "test actor did not reach barrier"
        threading.Event().wait(0.001)


class Call:
    def __init__(self, fn):
        self.result, self.error = None, None
        self.done = threading.Event()

        def run():
            try:
                self.result = fn()
            except BaseException as exc:
                self.error = exc
            finally:
                self.done.set()

        self.thread = threading.Thread(target=run)
        self.thread.start()

    def finish(self):
        self.thread.join(2)
        assert not self.thread.is_alive()
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def stable_wait(monkeypatch):
    m = importlib.import_module("ara.docx_analysis_worker.supervisor._dispatch_cells")
    monkeypatch.setattr(m, "monotonic_ns", lambda: 0)


def deliver(d, fn):
    call = Call(fn)
    until(lambda: d.view().publication_pending or call.done.is_set())
    if not call.done.is_set():
        d.step()
    return call.finish()


def test_construction_is_inert_and_snapshots_are_detached():
    a = api()
    before = set(threading.enumerate())
    d = a.create_dispatcher(
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
        Budget(300 * S, 15 * S, 0, 0),
        clock=lambda: pytest.fail("construction read clock"),
    )
    assert set(threading.enumerate()) == before
    assert d.view().control.phase == "open"
    assert isinstance(d.publication_port(), PublicationPort)
    assert d.publication_port() is d.publication_port()
    assert d.publication_port().view() == d.view().control
    with pytest.raises(FrozenInstanceError):
        d.view().stop_pending = True
    for obj in (d, d.publication_port()):
        assert "private" not in repr(obj)
        for clone in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                clone(obj)


@pytest.mark.parametrize("value", [None, True, 1, "private-sentinel"])
def test_invalid_factory_arguments(value):
    a = api()
    good = AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1)
    for identity, budget, clock in (
        (value, Budget(300 * S, 15 * S, 0, 0), lambda: 0),
        (good, value, lambda: 0),
        (good, Budget(300 * S, 15 * S, 0, 0), value),
    ):
        with pytest.raises(a.DispatchError) as e:
            a.create_dispatcher(identity, budget, clock=clock)
        assert e.value.code == "validation_error"
        assert "private-sentinel" not in str(e.value)


@pytest.mark.parametrize("field,value", [("claim_fence", 2), ("run_id", "x")])
def test_invalid_identity(field, value):
    a = api()
    identity = replace(AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1), **{field: value})
    with pytest.raises(a.DispatchError):
        a.create_dispatcher(identity, Budget(300 * S, 15 * S, 0, 0), clock=lambda: 0)


def test_owner_affinity_and_self_wait_are_rejected():
    d, _ = make()
    call = Call(d.step)
    with pytest.raises(api().DispatchError) as e:
        call.finish()
    assert e.value.code == "wrong_owner"
    with pytest.raises(api().DispatchError) as e:
        d.publication_port().reserve()
    assert e.value.code == "dispatch_busy"


def test_stop_coalesces_and_has_priority(stable_wait):
    d, _ = make(closed=True)
    port = d.publication_port()
    call = Call(port.reserve)
    until(lambda: d.view().publication_pending)
    for _ in range(1000):
        d.request_stop("user")
        d.request_stop("storage")
    assert d.view().stop_pending
    d.step()
    assert call.finish() is None
    assert d.view().control.stop_reason == "user"
    assert d.view().control.phase == "stopped"


@pytest.mark.parametrize("reason", [None, True, "private-sentinel", 1])
def test_invalid_stop_is_atomic(reason):
    d, _ = make()
    before = d.view()
    with pytest.raises(api().DispatchError):
        d.request_stop(reason)
    assert d.view() == before


def test_timely_heartbeat_is_anchored_once_and_receipt_is_separate():
    d, c = make(guard=50_000_000)
    c.value = 2 * S
    t = d.post_lease_ack(started_ns=S, received_ns=2 * S, remaining_lease_ns=15 * S)
    assert d.take_lease_result(t) is None
    assert d.view().control.lease_ns == 15 * S
    with pytest.raises(api().DispatchError) as e:
        d.post_lease_ack(started_ns=S, received_ns=2 * S, remaining_lease_ns=15 * S)
    assert e.value.code == "dispatch_busy"
    d.step()
    r = d.take_lease_result(t)
    assert r.accepted
    assert r.lease_ns == 15_950_000_000
    assert r.control.deadline_ns == 300 * S
    with pytest.raises(api().DispatchError):
        d.take_lease_result(t)
    for clone in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            clone(t)


@pytest.mark.parametrize("now", [15 * S, 16 * S, 301 * S])
def test_delayed_heartbeat_cannot_revive_old_lease(now):
    d, c = make()
    t = d.post_lease_ack(started_ns=S, received_ns=2 * S, remaining_lease_ns=15 * S)
    c.value = now
    d.step()
    assert not d.take_lease_result(t).accepted
    assert d.view().control.stop_requested
    assert d.view().control.lease_ns == 15 * S


@pytest.mark.parametrize(
    "s,r,duration",
    [
        (True, S, S),
        (-1, S, S),
        (2 * S, S, S),
        (0, 0, 0),
        (0, 0, 15 * S + 1),
        (2**63 - 1, 2**63 - 1, 1),
    ],
)
def test_invalid_heartbeat_is_atomic(s, r, duration):
    d, _ = make()
    before = d.view()
    with pytest.raises(api().DispatchError):
        d.post_lease_ack(started_ns=s, received_ns=r, remaining_lease_ns=duration)
    assert d.view() == before


@pytest.mark.parametrize("value", [True, -1, 1.5, 2**63, None])
def test_bad_clock_stops_without_exposing_exception(value):
    d, c = make()
    c.value = value
    d.step()
    assert d.view().fault == "clock"
    assert d.view().control.stop_requested
    assert d.view().control.stop_reason == "clock"


def test_backwards_and_raising_clock_are_fail_closed():
    for raising in (False, True):
        d, c = make()
        c.value = S
        d.step()
        c.value, c.error = 0, raising
        d.step()
        assert d.view().control.stop_reason == "clock"
        assert "private-sentinel" not in repr(d.view())


def test_no_permit_without_physical_notification(stable_wait):
    d, _ = make()
    assert deliver(d, d.publication_port().reserve) is None
    assert not d.view().control.child_closed


def test_unknown_rollback_reissue_and_old_token(stable_wait):
    d, _ = make(closed=True)
    p = d.publication_port()
    token = deliver(d, p.reserve)
    assert type(token) is CommitPermit
    assert deliver(d, lambda: p.settle(token, outcome="unknown")).phase == "unknown"
    assert deliver(d, p.reserve) is None
    assert deliver(d, lambda: p.settle(token, outcome="rolled_back")).phase == "open"
    fresh = deliver(d, p.reserve)
    assert fresh is not token
    with pytest.raises(ControlError) as e:
        deliver(d, lambda: p.settle(token, outcome="committed"))
    assert e.value.code == "invalid_permit"
    assert deliver(d, lambda: p.settle(fresh, outcome="committed")).phase == "succeeded"


def test_stop_after_taken_preserves_committed_even_when_clock_breaks(stable_wait):
    d, c = make(closed=True)
    p = d.publication_port()
    token = deliver(d, p.reserve)
    d.request_stop()
    c.error = True
    d.step()
    assert d.view().control.phase == "committing"
    assert deliver(d, lambda: p.settle(token, outcome="committed")).phase == "succeeded"
    d.step()
    assert d.view().control.phase == "succeeded"


def test_stop_then_rollback_never_reopens(stable_wait):
    d, _ = make(closed=True)
    p = d.publication_port()
    t = deliver(d, p.reserve)
    d.request_stop()
    d.step()
    assert deliver(d, lambda: p.settle(t, outcome="rolled_back")).phase == "stopped"
    assert deliver(d, p.reserve) is None


def test_reserve_timeout_is_abandoned_until_owner_cleanup():
    d, _ = make(closed=True)
    call = Call(d.publication_port().reserve)
    assert call.finish() is None
    assert d.view().publication_pending
    d.step()
    assert not d.view().publication_pending
    assert d.view().control.phase == "open"


def test_settlement_timeout_retains_commit_until_retry(monkeypatch, stable_wait):
    d, _ = make(closed=True)
    p = d.publication_port()
    t = deliver(d, p.reserve)
    cells = importlib.import_module("ara.docx_analysis_worker.supervisor._dispatch_cells")
    monkeypatch.setattr(cells, "monotonic_ns", time.monotonic_ns)
    call = Call(lambda: p.settle(t, outcome="committed"))
    with pytest.raises(DocumentError) as e:
        call.finish()
    assert e.value.code == "publication_in_progress"
    assert d.view().publication_pending
    fallback = Call(lambda: p.settle(t, outcome="unknown"))
    with pytest.raises(DocumentError):
        fallback.finish()
    d.step()
    assert d.view().control.phase == "succeeded"
    assert d.view().publication_pending
    monkeypatch.setattr(cells, "monotonic_ns", lambda: 0)
    assert deliver(d, lambda: p.settle(t, outcome="committed")).phase == "succeeded"
    assert not d.view().publication_pending


def test_foreign_ticket_and_forced_pid_change(monkeypatch):
    d, _ = make()
    other, _ = make()
    ticket = other.post_lease_ack(started_ns=0, received_ns=0, remaining_lease_ns=S)
    with pytest.raises(api().DispatchError) as e:
        d.take_lease_result(ticket)
    assert e.value.code == "invalid_handle"
    module = importlib.import_module("ara.docx_analysis_worker.supervisor.dispatcher")
    monkeypatch.setattr(module.os, "getpid", lambda: -1)
    for fn in (d.view, d.step, d.publication_port):
        with pytest.raises(api().DispatchError) as e:
            fn()
        assert e.value.code == "invalid_handle"
