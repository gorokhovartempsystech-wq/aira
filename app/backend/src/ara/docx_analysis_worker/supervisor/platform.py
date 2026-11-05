"""Trusted native adapters; transport observations never grant SQL authority."""

import os
from dataclasses import dataclass, field
from weakref import WeakSet

from ._runtime_models import SupervisorError


@dataclass(frozen=True, slots=True)
class NativeObservation:
    stage: str | None
    error_code: str | None
    physical_confirmed: bool
    candidate: bytes | None = field(repr=False)
    captured_ns: int | None = None


@dataclass(frozen=True, slots=True)
class CloseObservation:
    closed: bool
    physical_confirmed: bool


_ISSUED = WeakSet()
_KEY = object()


class _Resource:
    def __init__(self, key, port, kind, native, *, parent=None, budget=None):
        if key is not _KEY:
            raise TypeError("native wrappers are issued by adapters")
        self.pid, self.port, self.kind = os.getpid(), port, kind
        self.native, self.parent, self.budget = native, parent, budget
        self.closed = self.physical = False
        self.slot = None
        self.lease = budget.lease_ns if budget is not None else 0
        _ISSUED.add(self)

    def __repr__(self):
        return "<NativeResource>"

    def __reduce_ex__(self, protocol):
        raise TypeError("native wrappers are process-local")


class _NativePlatform:
    def __init__(self):
        self._clock = None

    def _resource(self, value, kind, *, closed=False):
        if (
            type(value) is not _Resource
            or value not in _ISSUED
            or value.pid != os.getpid()
            or value.port is not self
            or value.kind != kind
            or value.closed
            and not closed
        ):
            raise SupervisorError("invalid_handle")
        return value

    def clock(self):
        if self._clock is None:
            self._clock = self._backend().clock_factory()
        value = self._clock.now_ns()
        if type(value) is not int or not 0 <= value < 2**63:
            raise SupervisorError("clock_error")
        return value

    def acquire_owner(self, root):
        return _Resource(_KEY, self, "owner", self._backend().acquire_owner(root))

    def reserve_slot(self, owner):
        owner = self._resource(owner, "owner")
        if owner.slot is not None:
            raise SupervisorError("busy")
        slot = _Resource(_KEY, self, "slot", owner.native.reserve_slot(), parent=owner)
        owner.slot = slot
        return slot

    def launch(self, slot, identity, budget, *, request, execution_spec):
        slot = self._resource(slot, "slot")
        native = self._backend().start(
            slot.native, identity, budget, request=request, execution_spec=execution_spec
        )
        return _Resource(_KEY, self, "attempt", native, parent=slot, budget=budget)

    def observe(self, attempt):
        a = self._resource(attempt, "attempt")
        view = a.native.view()
        a.physical = bool(view.cleanup_confirmed and self._physical(view))
        raw = a.native.candidate()
        now = self.clock()
        if not (
            type(raw) is bytes and a.budget.last_ns <= now < min(a.lease, a.budget.deadline_ns)
        ):
            raw = None
        error = getattr(view, "error_code", None)
        return NativeObservation(
            view.stage,
            "runtime_unavailable" if error else None,
            a.physical,
            raw,
            now if raw is not None else None,
        )

    def renew(self, attempt, bound):
        a = self._resource(attempt, "attempt")
        accepted = a.native.renew(bound)
        if accepted is True:
            a.lease = bound
        return accepted is True

    def stop(self, attempt, reason):
        a = self._resource(attempt, "attempt", closed=True)
        if not a.closed:
            a.native.stop("protocol" if reason in ("clock", "child") else reason)

    def close_attempt(self, attempt):
        a = self._resource(attempt, "attempt", closed=True)
        if a.closed:
            return CloseObservation(True, a.physical)
        view = a.native.view()
        a.physical = a.physical or bool(view.cleanup_confirmed and self._physical(view))
        done = a.native.close(timeout=0)
        if done is True:
            a.closed = True
        return CloseObservation(done is True, a.physical)

    def release_slot(self, owner, slot):
        owner, slot = self._resource(owner, "owner"), self._resource(slot, "slot")
        if slot.parent is not owner or owner.slot is not slot:
            raise SupervisorError("invalid_handle")
        # Even False/exception can invalidate the underlying caller reference.
        slot.closed, owner.slot = True, None
        return owner.native.release_slot(slot.native) is True

    def close_owner(self, owner):
        owner = self._resource(owner, "owner")
        if owner.slot is not None:
            raise SupervisorError("busy")
        owner.native.close()
        owner.closed = True
