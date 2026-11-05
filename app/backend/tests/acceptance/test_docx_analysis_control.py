"""Frozen C1A behavior: explicit time, cancellation and publication arbitration."""

import copy
import importlib
import pickle
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest

MAX = 2**63 - 1
SECOND = 1_000_000_000


def api():
    return importlib.import_module("ara.docx_analysis_worker.control")


def identity():
    return api().AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1)


def controller(*, closed=False):
    a = api()
    c = a.AttemptControl(identity(), a.Budget(300 * SECOND, 15 * SECOND, 0, 0))
    if closed:
        c.mark_child_closed(now_ns=0)
    return c


def budget(**changes):
    args = dict(
        started_ns=SECOND,
        received_ns=2 * SECOND,
        remaining_deadline_ns=300 * SECOND,
        remaining_lease_ns=15 * SECOND,
    )
    return api().make_budget(**(args | changes))


def rejected(c, call, code="validation_error"):
    before = c.view()
    with pytest.raises(api().ControlError) as error:
        call()
    assert error.value.code == code
    assert c.view() == before


def test_explicit_budget_is_anchored_before_latency_and_guard_applied_once():
    b = budget()
    assert (b.deadline_ns, b.lease_ns, b.last_ns, b.guard_ns) == (
        300_950_000_000,
        15_950_000_000,
        2 * SECOND,
        50_000_000,
    )
    c = api().AttemptControl(identity(), b)
    c.tick(now_ns=3 * SECOND)
    assert c.view().deadline_ns == b.deadline_ns
    assert c.view().lease_ns == b.lease_ns
    assert budget(remaining_deadline_ns=1, remaining_lease_ns=1).deadline_ns == SECOND


@pytest.mark.parametrize(
    "change",
    [
        {"started_ns": True},
        {"received_ns": 1.0},
        {"started_ns": -1},
        {"received_ns": 0},
        {"remaining_deadline_ns": 0},
        {"remaining_deadline_ns": 300 * SECOND + 1},
        {"remaining_lease_ns": 15 * SECOND + 1},
        {"remaining_lease_ns": 0},
        {"remaining_lease_ns": True},
        {"remaining_deadline_ns": SECOND, "remaining_lease_ns": 2 * SECOND},
        {"guard_ns": -1},
        {"guard_ns": 50_000_001},
        {"guard_ns": False},
        {"started_ns": MAX, "received_ns": MAX},
        {"received_ns": MAX + 1},
    ],
)
def test_invalid_budget_parameters(change):
    with pytest.raises(api().ControlError) as error:
        budget(**change)
    assert error.value.code == "validation_error"


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "private-sentinel"),
        ("attempt_id", None),
        ("worker_instance_id", 2),
        ("claim_fence", True),
        ("claim_fence", 2),
    ],
)
def test_identity_revalidated(field, value):
    a = api()
    with pytest.raises(a.ControlError) as error:
        a.AttemptControl(replace(identity(), **{field: value}), budget())
    assert error.value.code == "validation_error"
    assert "private-sentinel" not in str(error.value)


@pytest.mark.parametrize("value", [None, {}, object()])
def test_wrong_budget_dto(value):
    with pytest.raises(api().ControlError):
        api().AttemptControl(identity(), value)


@pytest.mark.parametrize(
    "values",
    [
        (10, 11, 0, 0),
        (MAX, 1, 0, 0),
        (300 * SECOND, 16 * SECOND, 0, 0),
        (10, 1, False, 0),
        (10, 1, 0, 50_000_001),
    ],
)
def test_forged_budget_dto(values):
    a = api()
    with pytest.raises(a.ControlError):
        a.AttemptControl(identity(), a.Budget(*values))


def test_snapshots_are_frozen_and_view_does_not_advance_time():
    c = controller()
    v = c.view()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        v.phase = "succeeded"
    assert c.view() == v
    assert not hasattr(v, "__dict__")


@pytest.mark.parametrize(
    "now,reason", [(15 * SECOND, "lease"), (300 * SECOND, "deadline"), (301 * SECOND, "deadline")]
)
def test_expiry_boundaries(now, reason):
    c = controller(closed=True)
    v = c.tick(now_ns=now)
    assert (v.phase, v.stop_requested, v.stop_reason) == ("stopped", True, reason)
    assert c.reserve(now_ns=now) is None


def test_expired_initial_budget_and_backward_clock_are_irreversible():
    a = api()
    c = a.AttemptControl(identity(), a.Budget(10, 5, 5, 0))
    assert c.view().phase == "stopped"
    c = controller()
    c.tick(now_ns=SECOND)
    v = c.tick(now_ns=0)
    assert (v.phase, v.stop_reason, v.last_ns) == ("stopped", "clock", SECOND)
    c.acknowledge_lease(started_ns=SECOND, received_ns=2 * SECOND, remaining_lease_ns=15 * SECOND)
    assert c.view().phase == "stopped"


def test_live_lease_ack_shortens_or_extends_without_changing_deadline():
    c = controller()
    c.tick(now_ns=2 * SECOND)
    v = c.acknowledge_lease(
        started_ns=SECOND, received_ns=3 * SECOND, remaining_lease_ns=5 * SECOND
    )
    assert v.lease_ns == 6 * SECOND
    v = c.acknowledge_lease(
        started_ns=4 * SECOND, received_ns=5 * SECOND, remaining_lease_ns=15 * SECOND
    )
    assert v.lease_ns == 19 * SECOND
    assert v.deadline_ns == 300 * SECOND


@pytest.mark.parametrize("received", [15 * SECOND, 16 * SECOND])
def test_late_heartbeat_cannot_resurrect_previous_lease(received):
    c = controller()
    v = c.acknowledge_lease(
        started_ns=14 * SECOND, received_ns=received, remaining_lease_ns=15 * SECOND
    )
    assert v.phase == "stopped"
    assert v.lease_ns == 15 * SECOND


def test_new_lease_already_expired_stops_even_if_old_was_live():
    c = controller()
    v = c.acknowledge_lease(started_ns=0, received_ns=SECOND, remaining_lease_ns=1)
    assert v.phase == "stopped" and v.stop_reason == "lease"


@pytest.mark.parametrize("reason", ["user", "storage", "shutdown", "protocol", "child"])
def test_stop_before_publication_is_irreversible(reason):
    c = controller()
    c.request_stop(now_ns=1, reason=reason)
    c.mark_child_closed(now_ns=2)
    c.request_stop(now_ns=3, reason="deadline")
    v = c.view()
    assert v.child_closed and v.stop_requested and v.stop_reason == reason
    assert c.reserve(now_ns=4) is None


def test_single_permit_only_after_child_exit():
    c = controller()
    assert c.reserve(now_ns=0) is None
    c.mark_child_closed(now_ns=1)
    p = c.reserve(now_ns=1)
    assert isinstance(p, api().CommitPermit)
    assert c.reserve(now_ns=1) is None
    assert c.view().phase == "committing"


@pytest.mark.parametrize("unknown", [False, True])
def test_stop_after_permit_stays_pending_and_commit_wins(unknown):
    c = controller(closed=True)
    p = c.reserve(now_ns=0)
    if unknown:
        c.settle(p, outcome="unknown", now_ns=1)
    v = c.request_stop(now_ns=2)
    assert v.phase == ("unknown" if unknown else "committing")
    assert v.stop_requested
    v = c.settle(p, outcome="committed", now_ns=301 * SECOND)
    assert v.phase == "succeeded"
    assert c.request_stop(now_ns=302 * SECOND) == v
    assert c.settle(p, outcome="committed", now_ns=303 * SECOND) == v
    assert c.settle(p, outcome="unknown", now_ns=304 * SECOND) == v


@pytest.mark.parametrize("stop", [False, True])
def test_unknown_rollback_retries_only_without_stop(stop):
    c = controller(closed=True)
    p = c.reserve(now_ns=0)
    c.settle(p, outcome="unknown", now_ns=1)
    if stop:
        c.request_stop(now_ns=2)
    v = c.settle(p, outcome="rolled_back", now_ns=3)
    assert v.phase == ("stopped" if stop else "open")
    assert c.settle(p, outcome="rolled_back", now_ns=4).phase == v.phase
    assert c.settle(p, outcome="unknown", now_ns=4).phase == v.phase
    q = c.reserve(now_ns=5)
    if stop:
        assert q is None
    else:
        assert q is not p
        rejected(c, lambda: c.settle(p, outcome="committed", now_ns=6), "invalid_permit")
        assert c.view().deadline_ns == 300 * SECOND


def test_rollback_after_expiry_cannot_reopen():
    c = controller(closed=True)
    p = c.reserve(now_ns=0)
    assert c.settle(p, outcome="rolled_back", now_ns=15 * SECOND).phase == "stopped"
    assert c.reserve(now_ns=15 * SECOND) is None


@pytest.mark.parametrize("settled", ["committed", "rolled_back", "terminal"])
def test_conflicting_settlements_do_not_mutate(settled):
    c = controller(closed=True)
    p = c.reserve(now_ns=0)
    c.settle(p, outcome=settled, now_ns=1)
    for other in {"committed", "rolled_back", "terminal"} - {settled}:
        rejected(c, lambda: c.settle(p, outcome=other, now_ns=2), "conflicting_outcome")


def test_foreign_forged_permits_and_malformed_operations_are_atomic():
    c = controller(closed=True)
    p = c.reserve(now_ns=0)
    other = controller(closed=True).reserve(now_ns=0)
    forged = object.__new__(api().CommitPermit)
    for token in (None, object(), other, forged):
        rejected(c, lambda: c.settle(token, outcome="committed", now_ns=1), "invalid_permit")
    for call in (
        lambda: c.tick(now_ns=True),
        lambda: c.reserve(now_ns=-1),
        lambda: c.request_stop(now_ns=1, reason="private-sentinel"),
        lambda: c.settle(p, outcome="private-sentinel", now_ns=1),
        lambda: c.acknowledge_lease(started_ns=MAX, received_ns=MAX, remaining_lease_ns=SECOND),
    ):
        rejected(c, call)


@pytest.mark.parametrize("operation", [copy.copy, copy.deepcopy, pickle.dumps])
def test_control_and_permit_cannot_be_cloned(operation):
    c = controller(closed=True)
    p = c.reserve(now_ns=0)
    for value in (c, p):
        with pytest.raises((TypeError, api().ControlError)):
            operation(value)


def concurrent(a, b):
    barrier = Barrier(2)

    def call(f):
        barrier.wait(timeout=5)
        return f()

    with ThreadPoolExecutor(max_workers=2) as pool:
        x, y = pool.submit(call, a), pool.submit(call, b)
        return x.result(timeout=5), y.result(timeout=5)


def test_two_concurrent_publishers_receive_one_permit():
    c = controller(closed=True)
    values = concurrent(lambda: c.reserve(now_ns=1), lambda: c.reserve(now_ns=1))
    assert sum(v is not None for v in values) == 1


def test_stop_reserve_and_rollback_races_are_linearizable():
    c = controller(closed=True)
    _, p = concurrent(lambda: c.request_stop(now_ns=1), lambda: c.reserve(now_ns=1))
    assert c.view().stop_requested
    assert c.view().phase == ("committing" if p is not None else "stopped")
    if p is not None:
        concurrent(
            lambda: c.request_stop(now_ns=2), lambda: c.settle(p, outcome="rolled_back", now_ns=2)
        )
        assert c.view().phase == "stopped"
    assert c.reserve(now_ns=3) is None


def test_heartbeat_against_expiry_cannot_revive_expired_control():
    c = controller()
    concurrent(
        lambda: c.tick(now_ns=15 * SECOND),
        lambda: c.acknowledge_lease(
            started_ns=14 * SECOND, received_ns=15 * SECOND, remaining_lease_ns=15 * SECOND
        ),
    )
    assert c.view().phase == "stopped"


def test_fresh_import_and_construction_have_no_runtime_io():
    script = r"""
import builtins, importlib, os, socket, subprocess, threading, time
from dataclasses import dataclass
from uuid import UUID
def forbidden(*a, **kw): raise AssertionError("runtime IO")
builtins.open = forbidden
os.getenv = forbidden
os._Environ.__getitem__ = forbidden
socket.socket = forbidden
subprocess.Popen = forbidden
threading.Thread.start = forbidden
time.time = time.monotonic = time.monotonic_ns = time.perf_counter = forbidden
a = importlib.import_module("ara.docx_analysis_worker.control")
c = a.AttemptControl(a.AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
                     a.Budget(100, 10, 0, 0))
assert c.view().phase == "open"
assert not any(n.startswith(("sqlalchemy", "psycopg", "onnxruntime", "ara.models"))
               for n in __import__("sys").modules)
"""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root / "src", capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr.decode()
