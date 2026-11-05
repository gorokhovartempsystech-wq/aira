"""Explicit Windows fixture transport. No SQL, model imports or implicit runtime."""

import base64
import hashlib
import math
import os
import threading
import time
from weakref import WeakSet

from ..control import Budget
from ..control._budget import identity_values, validate_budget
from ..wire import WireBinding, encode_message
from . import _control_writer, _data_pump, _launch_worker
from ._adopt import MODES
from ._attempt_state import State
from ._clock import WindowsClock
from ._driver_models import Command
from ._errors import LocalResource, WindowsRuntimeError
from ._launch import prepare_fixture_guardian
from ._locks import _SLOTS, SlotLease

_KEY, _ISSUED, _REGISTRY = object(), WeakSet(), {}
_MUTEX = threading.Lock()
_REASONS = ("user", "deadline", "lease", "storage", "shutdown", "protocol")


class WindowsAttempt(LocalResource):
    def __new__(cls, key=None, *args):
        if key is not _KEY:
            raise TypeError("attempts are issued by the fixture factory")
        return super().__new__(cls)

    def __init__(self, key, state):
        if key is not _KEY or self in _ISSUED:
            raise TypeError("attempts are issued once")
        self._state, self._pid = state, os.getpid()
        _ISSUED.add(self)

    def _check(self):
        if type(self) is not WindowsAttempt or self not in _ISSUED or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")

    def view(self):
        self._check()
        return self._state.view()

    def candidate(self):
        self._check()
        s = self._state
        with s.cv:
            if s.closing or s.released:
                return None
        if s.tick() is None:
            return None
        with s.cv:
            return s.reply if s.candidate_locked() else None

    def stop(self, reason="user"):
        self._check()
        if type(reason) is not str or reason not in _REASONS:
            raise WindowsRuntimeError("validation_error")
        self._state.stop(hard=reason == "protocol")

    def renew(self, lease_ns):
        self._check()
        if type(lease_ns) is not int or not 0 <= lease_ns < 2**63:
            raise WindowsRuntimeError("validation_error")
        s = self._state
        now = s.tick()
        with s.cv:
            if (
                now is None
                or s.stopped
                or s.closing
                or s.natural
                or not s.permit_ready
                or s.command
            ):
                return False
            if not s.lease <= lease_ns <= min(s.deadline, now + 15_000_000_000) or lease_ns <= now:
                raise WindowsRuntimeError("validation_error")
            cmd = Command(lease_ns, s.lease, min(now + 50_000_000, s.lease, s.deadline))
            s.command = cmd
            s.cv.notify_all()
        while True:
            now = s.tick()
            with s.cv:
                if cmd.outcome != "pending":
                    return cmd.outcome == "accepted"
                if cmd.receipt and now is not None and now < cmd.cutoff and not s.stopped:
                    s.lease, cmd.outcome = cmd.lease, "accepted"
                    s.cv.notify_all()
                    return True
                s.cv.wait(0.005)

    def close(self, timeout=5.0):
        self._check()
        if (
            type(timeout) not in (int, float)
            or not 0 <= timeout <= 30
            or not math.isfinite(timeout)
        ):
            raise WindowsRuntimeError("validation_error")
        s = self._state
        with s.cv:
            if s.released:
                return True
            natural = s.natural and not (s.stopped or s.error)
            s.closing = True
            s.reply = None
            s.cv.notify_all()
        if not natural:
            s.stop()
        end = time.monotonic() + timeout
        for name, thread in s.threads.items():
            if s.started.get(name) == "started" or thread.is_alive():
                thread.join(max(0, end - time.monotonic()))
        with s.cv:
            done = (
                s.resources_closed
                and all(s.done.values())
                and all(not t.is_alive() for t in s.threads.values())
            )
            if not done:
                s.timed_out = True
                if s.error is None:
                    s.error = "shutdown_timeout"
                return False
            s.released, s.frame, s.reply = True, None, None
            s.timed_out = False
        with _MUTEX:
            _REGISTRY.pop(id(self), None)
        return True


def _actor(state, name, target):
    try:
        target(state)
    except BaseException:
        state.stop("transport", True)
        with state.cv:
            state.blocked = True
    finally:
        with state.cv:
            state.done[name] = True
            state.cv.notify_all()


def start_fixture_attempt(slot, identity, budget, *, request, execution_spec, mode="success"):
    try:
        run, attempt, worker, fence = identity_values(identity)
        budget = Budget(*validate_budget(budget))
        if (
            type(slot) is not SlotLease
            or slot not in _SLOTS
            or type(request) is not bytes
            or not 1 <= len(request) <= 8 * 1024 * 1024
            or type(execution_spec) is not bytes
            or not 1 <= len(execution_spec) <= 4096
            or type(mode) is not str
            or mode not in MODES
        ):
            raise ValueError()
        slot.handle()
        binding = WireBinding(run, attempt)
        spec_sha = hashlib.sha256(execution_spec).hexdigest()
        frame = encode_message(
            binding,
            kind="run",
            seq=0,
            values={
                "worker_instance_id": str(worker),
                "claim_fence": fence,
                "request_sha256": hashlib.sha256(request).hexdigest(),
                "execution_spec_sha256": spec_sha,
                "request_b64": base64.b64encode(request).decode(),
                "execution_spec_b64": base64.b64encode(execution_spec).decode(),
            },
        )
    except Exception:
        raise WindowsRuntimeError("validation_error") from None
    clock = WindowsClock()
    now = clock.now_ns()
    if not (
        budget.last_ns <= now < budget.lease_ns <= budget.deadline_ns
        and budget.deadline_ns - now <= 300_000_000_000
        and budget.lease_ns - now <= 15_000_000_000
    ):
        raise WindowsRuntimeError("runtime_unavailable")
    with _MUTEX:
        if _REGISTRY:
            raise WindowsRuntimeError("runtime_busy")
        holder = prepare_fixture_guardian(
            slot,
            binding,
            deadline_ns=budget.deadline_ns,
            lease_ns=budget.lease_ns,
            mode=mode,
        )
        state = State(
            holder, binding, budget, frame, spec_sha, clock, fixture=mode != "local_model"
        )
        obj = WindowsAttempt(_KEY, state)
        _REGISTRY[id(obj)] = obj
    targets = {"launch": _launch_worker.run, "control": _control_writer.run, "data": _data_pump.run}
    try:
        for name, target in targets.items():
            state.threads[name] = threading.Thread(
                target=_actor,
                args=(state, name, target),
                name="aira-fixture-" + name,
                daemon=True,
            )
        for name, thread in state.threads.items():
            state.started[name] = "unknown"
            thread.start()
            state.started[name] = "started"
        with state.cv:
            state.gate = True
            state.cv.notify_all()
    except Exception:
        with state.cv:
            state.gate = False
            for name in targets:
                if name not in state.started:
                    state.done[name] = True
                    if name in state.quiescent:
                        state.quiescent[name] = True
            state.cv.notify_all()
        state.stop("transport", True)
    return obj
