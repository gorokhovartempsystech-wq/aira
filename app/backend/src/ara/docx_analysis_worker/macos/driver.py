"""Explicit synthetic parent driver; candidate bytes still require B1/B2/SQL validation."""

import base64
import hashlib
import os
from weakref import WeakSet

from ..control import Budget
from ..control._budget import identity_values, validate_budget
from ..wire import WireBinding, encode_message
from . import _launch
from ._clock import DarwinClock
from ._control_pipe import ControlPipe
from ._data_pump import DataPump
from ._errors import LocalResource, MacRuntimeError

_ISSUE = object()
_ISSUED = WeakSet()


class MacAttempt(LocalResource):
    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("attempts are issued by the fixture factory")
        return super().__new__(cls)

    def __init__(self, key, pump):
        if key is not _ISSUE or self in _ISSUED:
            raise TypeError("attempts are issued once")
        self._pump, self._pid = pump, os.getpid()
        _ISSUED.add(self)

    def _check(self):
        if type(self) is not MacAttempt or self not in _ISSUED or self._pid != os.getpid():
            raise MacRuntimeError("invalid_handle")

    def view(self):
        self._check()
        return self._pump.view()

    def candidate(self):
        self._check()
        return self._pump.candidate()

    def renew(self, lease_ns):
        self._check()
        return self._pump.control.renew(lease_ns)

    def stop(self, reason="user"):
        self._check()
        self._pump.control.stop(reason)

    def close(self, timeout=5.0):
        self._check()
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise MacRuntimeError("validation_error")
        if self._pump.thread.is_alive():
            if self._pump.view().phase not in ("closed", "blocked"):
                self.stop("shutdown")
            self._pump.thread.join(timeout)
        if self._pump.thread.is_alive() or self._pump.holder.process.poll() is None:
            return False
        self._pump.holder.close()
        self._pump.discard()
        return True


def start_fixture_attempt(slot, identity, budget, *, request, execution_spec, mode="success"):
    try:
        run_id, attempt_id, worker_id, fence = identity_values(identity)
        budget = Budget(*validate_budget(budget))
        if (
            type(request) is not bytes
            or not 1 <= len(request) <= 8 * 1024 * 1024
            or type(execution_spec) is not bytes
            or not 1 <= len(execution_spec) <= 4096
            or type(mode) is not str
            or mode not in _launch.MODES
        ):
            raise ValueError()
        binding = WireBinding(run_id, attempt_id)
        spec_sha = hashlib.sha256(execution_spec).hexdigest()
        frame = encode_message(
            binding,
            kind="run",
            seq=0,
            values=dict(
                worker_instance_id=str(worker_id),
                claim_fence=fence,
                request_sha256=hashlib.sha256(request).hexdigest(),
                execution_spec_sha256=spec_sha,
                request_b64=base64.b64encode(request).decode(),
                execution_spec_b64=base64.b64encode(execution_spec).decode(),
            ),
        )
    except Exception:
        raise MacRuntimeError("validation_error") from None
    clock = DarwinClock()
    now = clock.now_ns()
    if not (
        budget.last_ns <= now < budget.lease_ns <= budget.deadline_ns
        and budget.deadline_ns - now <= 300_000_000_000
        and budget.lease_ns - now <= 15_000_000_000
    ):
        raise MacRuntimeError("runtime_unavailable")
    holder = _launch.launch_fixture_guardian(
        slot, binding, deadline_ns=budget.deadline_ns, lease_ns=budget.lease_ns, mode=mode
    )
    try:
        control = ControlPipe(holder, binding, budget, clock)
        pump = DataPump(
            holder, control, binding, spec_sha, frame, clock, fixture=mode != "local_model"
        )
        result = MacAttempt(_ISSUE, pump)
        pump.thread.start()
        return result
    except Exception:
        holder.close()
        try:
            holder.process.wait(timeout=5)
        except Exception:
            pass
        raise MacRuntimeError("runtime_unavailable") from None
