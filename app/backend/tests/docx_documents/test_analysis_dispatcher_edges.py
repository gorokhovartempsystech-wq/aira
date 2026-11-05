"""Fault delivery barriers and lifetime edges for the F1 adapter."""

import importlib
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ara.documents.storage import DocumentError
from ara.docx_analysis_worker.control import ControlError
from ara.docx_analysis_worker.supervisor import AttemptDispatcher, DispatchError, LeaseTicket
from tests.acceptance.test_docx_analysis_dispatcher import Call, deliver, make, until


@pytest.fixture
def stable_wait(monkeypatch):
    cells = importlib.import_module("ara.docx_analysis_worker.supervisor._dispatch_cells")
    monkeypatch.setattr(cells, "monotonic_ns", lambda: 0)


def late_receipt(monkeypatch, d, clock):
    original = d._cv.wait
    armed = [True]

    def wait(timeout=None):
        result = original(timeout)
        if armed[0]:
            # No barrier or wait while holding the cell mutex.
            clock.value += 50_000_000
            armed[0] = False
        return result

    monkeypatch.setattr(d._cv, "wait", wait)


def test_offered_but_late_permit_is_never_delivered(monkeypatch, stable_wait):
    d, clock = make(closed=True)
    late_receipt(monkeypatch, d, clock)
    call = Call(d.publication_port().reserve)
    until(lambda: d.view().publication_pending)
    d.step()
    assert call.finish() is None
    assert d.view().control.phase == "committing"
    assert d.view().publication_pending
    d.step()
    assert d.view().control.phase == "open"
    assert not d.view().publication_pending
    fresh = deliver(d, d.publication_port().reserve)
    assert fresh is not None


def test_stop_during_abandoned_offer_cleanup_remains_stopped(monkeypatch, stable_wait):
    d, clock = make(closed=True)
    late_receipt(monkeypatch, d, clock)
    call = Call(d.publication_port().reserve)
    until(lambda: d.view().publication_pending)
    d.step()
    assert call.finish() is None
    d.request_stop()
    d.step()
    assert d.view().control.phase == "stopped"
    assert not d.view().publication_pending
    assert deliver(d, d.publication_port().reserve) is None


def test_committed_settle_ack_lost_after_transition(monkeypatch, stable_wait):
    d, clock = make(closed=True)
    p = d.publication_port()
    t = deliver(d, p.reserve)
    late_receipt(monkeypatch, d, clock)
    call = Call(lambda: p.settle(t, outcome="committed"))
    until(lambda: d.view().publication_pending)
    d.step()
    with pytest.raises(DocumentError) as e:
        call.finish()
    assert e.value.code == "publication_in_progress"
    assert d.view().control.phase == "succeeded"
    assert d.view().publication_pending
    conflict = Call(lambda: p.settle(t, outcome="unknown"))
    with pytest.raises(DocumentError):
        conflict.finish()
    assert deliver(d, lambda: p.settle(t, outcome="committed")).phase == "succeeded"
    assert deliver(d, lambda: p.settle(t, outcome="unknown")).phase == "succeeded"


def test_taken_token_survives_many_ticks_and_caller_loss(stable_wait):
    d, clock = make(closed=True)
    p = d.publication_port()
    t = deliver(d, p.reserve)
    clock.value = 301_000_000_000
    before = set(threading.enumerate())
    for _ in range(1000):
        d.step()
        d.view()
        d.post_child_closed()
    assert set(threading.enumerate()) == before
    assert d.view().control.phase == "committing"
    assert d.view().control.stop_requested
    assert deliver(d, p.reserve) is None
    assert deliver(d, lambda: p.settle(t, outcome="committed")).phase == "succeeded"


@pytest.mark.parametrize("outcome", ["committed", "rolled_back", "terminal"])
def test_resolved_fact_replays_and_rejects_conflict(outcome, stable_wait):
    d, _ = make(closed=True)
    p = d.publication_port()
    t = deliver(d, p.reserve)
    expected = deliver(d, lambda: p.settle(t, outcome=outcome))
    assert deliver(d, lambda: p.settle(t, outcome=outcome)) == expected
    assert deliver(d, lambda: p.settle(t, outcome="unknown")) == expected
    incompatible = "rolled_back" if outcome != "rolled_back" else "committed"
    with pytest.raises(ControlError) as e:
        deliver(d, lambda: p.settle(t, outcome=incompatible))
    assert e.value.code == "conflicting_outcome"
    assert d.view().control == expected


@pytest.mark.parametrize("outcome", [None, True, 1, "private-sentinel"])
def test_invalid_outcome_does_not_poison_current_token(outcome, stable_wait):
    d, _ = make(closed=True)
    p = d.publication_port()
    t = deliver(d, p.reserve)
    with pytest.raises(ControlError):
        deliver(d, lambda: p.settle(t, outcome=outcome))
    assert deliver(d, lambda: p.settle(t, outcome="committed")).phase == "succeeded"


def test_forged_constructors_and_handles():
    from ara.docx_analysis_worker.supervisor.publication_port import DispatcherPublicationPort

    for cls in (AttemptDispatcher, LeaseTicket):
        with pytest.raises(TypeError):
            cls()
    forged = object.__new__(AttemptDispatcher)
    with pytest.raises(DispatchError) as e:
        forged.view()
    assert e.value.code == "invalid_handle"
    port = object.__new__(DispatcherPublicationPort)
    with pytest.raises(DispatchError):
        port.view()


def test_no_step_owner_takeover_after_thread_exit():
    from uuid import UUID

    from ara.docx_analysis_worker.control import AttemptIdentity, Budget
    from ara.docx_analysis_worker.supervisor import create_dispatcher

    d = create_dispatcher(
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
        Budget(300_000_000_000, 15_000_000_000, 0, 0),
        clock=lambda: 0,
    )
    Call(d.step).finish()
    with pytest.raises(DispatchError) as e:
        Call(d.step).finish()
    assert e.value.code == "wrong_owner"


def test_smaller_and_future_lease_receipts_are_rejected():
    for s, r in ((0, 0), (2_000_000_000, 3_000_000_000)):
        d, _ = make()
        t = d.post_lease_ack(started_ns=s, received_ns=r, remaining_lease_ns=1_000_000_000)
        d.step()
        decision = d.take_lease_result(t)
        assert not decision.accepted
        assert decision.lease_ns == 15_000_000_000


def test_stop_prevents_pending_heartbeat_extension():
    d, clock = make()
    clock.value = 2_000_000_000
    t = d.post_lease_ack(
        started_ns=1_000_000_000, received_ns=clock.value, remaining_lease_ns=15_000_000_000
    )
    d.request_stop()
    d.step()
    assert not d.take_lease_result(t).accepted
    assert d.view().control.phase == "stopped"


def test_reentrant_step_is_busy_without_transfer_of_owner():
    d, clock = make()

    def sample():
        with pytest.raises(DispatchError) as e:
            d.step()
        assert e.value.code == "dispatch_busy"
        return clock.value

    d._clock = sample
    d.step()
    assert d.view().control.phase == "open"


def test_port_concurrent_caller_is_busy(stable_wait):
    d, _ = make(closed=True)
    p = d.publication_port()
    first = Call(p.reserve)
    until(lambda: d.view().publication_pending)
    second = Call(p.reserve)
    with pytest.raises(DocumentError) as e:
        second.finish()
    assert e.value.code == "publication_in_progress"
    d.step()
    assert first.finish() is not None


def test_snapshot_mutation_cannot_change_identity_or_deadline():
    d, _ = make()
    before = d.view()
    exposed = d.publication_port().view()
    object.__setattr__(exposed.identity, "claim_fence", 99)
    object.__setattr__(exposed, "deadline_ns", 2**63)
    assert d.view() == before


def test_fresh_process_import_does_not_spawn_or_read_secrets():
    source = """
import pathlib, threading, socket, subprocess
from unittest.mock import patch
from contextlib import ExitStack
import os
import sys
sys.path.insert(0, str(pathlib.Path.cwd() / "src"))
# Load dependencies before guarding this package's import.
import ara.docx_analysis_runs.guarded_port
import ara.docx_analysis_worker.control
before = set(threading.enumerate())
def denied(*a, **kw):
    raise AssertionError("unexpected external operation")
with ExitStack() as stack:
    for target in ("threading.Thread.start", "socket.socket", "subprocess.Popen",
                   "dotenv.load_dotenv", "sqlalchemy.engine.Engine.connect"):
        stack.enter_context(patch(target, denied))
    import ara.docx_analysis_worker.supervisor
assert set(threading.enumerate()) == before
print("inert")
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "inert"


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork capability test requires POSIX")
def test_real_fork_cannot_reuse_dispatcher():
    d, _ = make()
    read, write = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read)
        try:
            d.view()
            os.write(write, b"bad")
        except DispatchError as error:
            os.write(write, error.code.encode())
        finally:
            os.close(write)
            os._exit(0)
    os.close(write)
    try:
        response = os.read(read, 64)
    finally:
        os.close(read)
        _, status = os.waitpid(child, 0)
    assert status == 0
    assert response == b"invalid_handle"


def test_caller_sample_before_owner_tick_is_not_clock_regression(stable_wait):
    d, clock = make(closed=True)
    owner = threading.current_thread()
    entered, release = threading.Event(), threading.Event()
    first = [True]

    def sample():
        if threading.current_thread() is not owner and first[0]:
            first[0] = False
            value = clock.value
            entered.set()
            assert release.wait(2)
            return value
        return clock.value

    d._clock = sample
    call = Call(d.publication_port().reserve)
    assert entered.wait(2)
    clock.value = 1
    d.step()
    release.set()
    until(lambda: d.view().publication_pending or call.done.is_set())
    d.step()
    assert call.finish() is not None
    assert d.view().fault is None


def test_offer_receipt_cannot_outlive_actual_lease(monkeypatch, stable_wait):
    from uuid import UUID

    from ara.docx_analysis_worker.control import AttemptIdentity, Budget
    from ara.docx_analysis_worker.supervisor import create_dispatcher
    from tests.acceptance.test_docx_analysis_dispatcher import Clock

    clock = Clock()
    d = create_dispatcher(
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
        Budget(300_000_000_000, 10_000_000, 0, 0),
        clock=clock,
    )
    d.post_child_closed()
    d.step()
    original = d._cv.wait

    def wait(timeout=None):
        result = original(timeout)
        clock.value = 10_000_000  # lease expires before the 50ms receipt budget
        return result

    monkeypatch.setattr(d._cv, "wait", wait)
    call = Call(d.publication_port().reserve)
    until(lambda: d.view().publication_pending)
    d.step()
    assert call.finish() is None
    d.step()
    assert d.view().control.phase == "stopped"
