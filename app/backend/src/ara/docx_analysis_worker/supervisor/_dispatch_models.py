"""Detached metadata and process-local lease receipts."""

import os
from dataclasses import dataclass
from weakref import WeakSet

from ..control import ControlView
from ..control._models import Uncopyable

_KEY = object()
_TICKETS = WeakSet()


class DispatchError(Exception):
    def __init__(self, code="validation_error"):
        self.code = (
            code
            if code in {"validation_error", "invalid_handle", "wrong_owner", "dispatch_busy"}
            else "validation_error"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class DispatchView:
    control: ControlView
    stop_pending: bool
    lease_pending: bool
    child_pending: bool
    publication_pending: bool
    fault: str | None


@dataclass(frozen=True, slots=True)
class LeaseDecision:
    accepted: bool
    lease_ns: int
    control: ControlView


class LeaseTicket(Uncopyable):
    def __new__(cls, key=None):
        if key is not _KEY:
            raise TypeError("lease tickets are issued by a dispatcher")
        return super().__new__(cls)

    def __init__(self, key=None):
        if key is not _KEY or self in _TICKETS:
            raise TypeError("lease tickets are issued once")
        self._pid = os.getpid()
        _TICKETS.add(self)

    def __repr__(self):
        return "<LeaseTicket>"
