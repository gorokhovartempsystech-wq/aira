"""D3: private transport candidate needs stream, exit and live-budget evidence."""

import copy
import importlib
import os
import pickle
import time
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from uuid import UUID

import pytest

from ara.docx_analysis_worker.control import AttemptIdentity, Budget, make_budget
from ara.docx_analysis_worker.wire import StreamDecoder, WireBinding
from tests.acceptance.test_docx_analysis_macos_primitives import api, native, reject, root

__all__ = ["native", "root"]
IDENTITY = AttemptIdentity(UUID(int=201), UUID(int=202), UUID(int=203), 1)
BINDING = WireBinding(IDENTITY.run_id, IDENTITY.attempt_id)


def driver():
    return importlib.import_module("ara.docx_analysis_worker.macos.driver")


def wait_for(attempt, predicate, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        view = attempt.view()
        if predicate(view):
            return view
        time.sleep(0.01)
    pytest.fail("synthetic attempt readiness timeout")


def start(root, mode="success", request=b"private-sentinel", lease=3_000_000_000):
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    now = api().DarwinClock().now_ns()
    budget = make_budget(
        started_ns=now,
        received_ns=now,
        remaining_deadline_ns=6_000_000_000,
        remaining_lease_ns=lease,
    )
    try:
        attempt = driver().start_fixture_attempt(
            slot, IDENTITY, budget, request=request, execution_spec=b"synthetic-spec", mode=mode
        )
        return owner, slot, attempt
    except BaseException:
        owner.abandon()
        raise


def cleanup(owner, slot, attempt):
    assert attempt.close(timeout=8)
    assert owner.release_slot(slot)
    owner.close()


def test_native_candidate_and_private_immutable_view(native, root):
    owner, slot, attempt = start(root)
    try:
        view = wait_for(attempt, lambda v: v.phase in ("closed", "blocked"))
        assert view.phase == "closed" and view.cleanup_confirmed and view.fixture
        assert view.exit_kind == "clean" and view.exit_code == 0
        assert view.candidate_ready and view.error_code is None
        value = attempt.candidate()
        assert value == b"fixture-response" and attempt.candidate() is value
        assert "private-sentinel" not in repr(view) + repr(attempt)
        with pytest.raises((FrozenInstanceError, AttributeError)):
            view.cleanup_confirmed = False
        for call in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                call(attempt)
    finally:
        cleanup(owner, slot, attempt)


@pytest.mark.parametrize("mode", ["nonzero", "tail", "error", "stderr_flood", "result_hang"])
def test_native_invalid_success_never_candidate(native, root, mode):
    owner, slot, attempt = start(root, mode, lease=900_000_000)
    try:
        view = wait_for(attempt, lambda v: v.phase in ("closed", "blocked"))
        assert not view.candidate_ready and attempt.candidate() is None
        assert view.error_code is not None or view.stop_requested
    finally:
        cleanup(owner, slot, attempt)


def test_native_stop_with_large_request(native, root):
    owner, slot, attempt = start(root, "wait", request=b"x" * (8 * 1024 * 1024))
    try:
        attempt.stop()
        attempt.stop()
        view = wait_for(attempt, lambda v: v.phase in ("closed", "blocked"))
        assert view.stop_requested and attempt.candidate() is None
    finally:
        cleanup(owner, slot, attempt)


def test_stop_after_transport_close_revokes_unpublished_candidate(native, root):
    owner, slot, attempt = start(root)
    try:
        wait_for(attempt, lambda v: v.phase == "closed")
        assert attempt.candidate() == b"fixture-response"
        attempt.stop()
        assert attempt.candidate() is None and attempt.view().stop_requested
    finally:
        cleanup(owner, slot, attempt)


def test_native_renew_and_invalid_reason_no_mutation(native, root):
    owner, slot, attempt = start(root, "wait")
    try:
        wait_for(attempt, lambda v: v.stage == "analyzing")
        reject("validation_error", lambda: attempt.stop("arbitrary"))
        reject("validation_error", lambda: attempt.renew(True))
        assert not attempt.view().stop_requested
        assert attempt.renew(api().DarwinClock().now_ns() + 2_000_000_000)
        attempt.stop("shutdown")
        assert not attempt.renew(api().DarwinClock().now_ns() + 2_000_000_000)
    finally:
        cleanup(owner, slot, attempt)


def test_local_validation_and_expired_budget_do_not_launch(native, root, monkeypatch):
    impl = importlib.import_module("ara.docx_analysis_worker.macos._launch")
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()

    def forbidden(*a, **k):
        raise AssertionError("unexpected spawn")

    monkeypatch.setattr(impl, "launch_fixture_guardian", forbidden)
    now = api().DarwinClock().now_ns()
    budget = Budget(now + 1_000_000_000, now + 500_000_000, now, 0)
    try:
        for values in (dict(request=b""), dict(execution_spec=b"x" * 4097), dict(mode="arbitrary")):
            args = dict(request=b"x", execution_spec=b"y") | values
            reject(
                "validation_error",
                lambda: driver().start_fixture_attempt(slot, IDENTITY, budget, **args),
            )
        reject(
            "runtime_unavailable",
            lambda: driver().start_fixture_attempt(
                slot, IDENTITY, Budget(now, now, now, 0), request=b"x", execution_spec=b"y"
            ),
        )
        assert owner.release_slot(slot)
    finally:
        owner.abandon()


def control():
    module = importlib.import_module("ara.docx_analysis_worker.macos._control_pipe")
    reader, writer = os.pipe()
    os.set_blocking(writer, False)
    remaining = [writer]

    def close():
        if remaining:
            os.close(remaining.pop())

    clock = SimpleNamespace(value=100)
    clock.now_ns = lambda: clock.value
    holder = SimpleNamespace(control_fd=writer, close_control=close)
    port = module.ControlPipe(holder, BINDING, Budget(1000, 500, 100, 0), clock)
    return port, clock, reader, close


def test_control_sequences_atomic_and_no_budget_extension():
    port, clock, reader, close = control()
    try:
        clock.value = 200
        assert port.renew(600)
        port.stop("user")
        raw = os.read(reader, 4096)
        decoder = StreamDecoder(BINDING, lane="control")
        values = decoder.feed(raw)
        decoder.finish()
        assert [m.kind for m in values] == ["permit", "permit", "stop"]
        assert [m.seq for m in values] == [0, 1, 2]
        assert [m.values["deadline_ns"] for m in values[:2]] == [1000, 1000]
        assert not port.renew(700)
    finally:
        close()
        os.close(reader)


def test_control_late_renew_and_backpressure_fail_closed(monkeypatch):
    port, clock, reader, close = control()
    try:
        clock.value = 500
        reject("runtime_unavailable", lambda: port.renew(800))
        assert port.stop_requested and port.error_code == "lease"
    finally:
        close()
        os.close(reader)
    port, clock, reader, close = control()
    try:

        def blocked(*a):
            raise BlockingIOError()

        with monkeypatch.context() as patch:
            patch.setattr(os, "write", blocked)
            reject("runtime_unavailable", lambda: port.renew(600))
        assert port.stop_requested and port.error_code == "transport"
    finally:
        close()
        os.close(reader)
