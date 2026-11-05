"""Explicit single-owner C1A dispatcher: no threads, database or process operations."""

import os
from dataclasses import replace
from threading import Condition, Lock, current_thread
from weakref import WeakSet

from ..control import AttemptControl, ControlError
from ..control._budget import integer, total
from ..control._controller import REASONS
from ..control._models import Uncopyable
from ._dispatch_cells import LeaseCell, ReserveCell, SettleCell
from ._dispatch_models import (
    _KEY,
    _TICKETS,
    DispatchError,
    DispatchView,
    LeaseDecision,
    LeaseTicket,
)

_ISSUED = WeakSet()


class AttemptDispatcher(Uncopyable):
    def __new__(cls, key=None, *args, **kwargs):
        if key is not _KEY:
            raise TypeError("dispatchers are issued by the factory")
        return super().__new__(cls)

    def __init__(self, key, control, clock):
        if key is not _KEY or self in _ISSUED:
            raise TypeError("dispatchers are issued once")
        self._pid, self._control, self._clock = os.getpid(), control, clock
        self._cv, self._step_guard, self._caller_guard = Condition(), Lock(), Lock()
        self._owner = None
        self._current = control.view()
        self._stop_seen = self._stop_pending = None
        self._child = False
        self._lease = self._cell = self._token = None
        self._taken = False
        self._fault = None
        from .publication_port import DispatcherPublicationPort

        self._port = DispatcherPublicationPort(_KEY, self)
        _ISSUED.add(self)

    def __repr__(self):
        return "<AttemptDispatcher>"

    def _check(self):
        if type(self) is not AttemptDispatcher or self not in _ISSUED or self._pid != os.getpid():
            raise DispatchError("invalid_handle")

    def _copy_control(self):
        return replace(self._current, identity=replace(self._current.identity))

    def view(self):
        self._check()
        with self._cv:
            return DispatchView(
                self._copy_control(),
                bool(self._stop_pending),
                self._lease is not None,
                self._child,
                self._cell is not None,
                self._fault,
            )

    def publication_port(self):
        self._check()
        return self._port

    def _stop_locked(self, reason):
        if self._stop_seen is None:
            self._stop_seen = self._stop_pending = reason
        self._cv.notify_all()

    def request_stop(self, reason="user"):
        self._check()
        if type(reason) is not str or reason not in REASONS:
            raise DispatchError()
        with self._cv:
            self._stop_locked(reason)

    def post_child_closed(self):
        self._check()
        with self._cv:
            if not self._current.child_closed:
                self._child = True

    def post_lease_ack(self, *, started_ns, received_ns, remaining_lease_ns):
        self._check()
        try:
            s, r = integer(started_ns), integer(received_ns)
            duration = integer(remaining_lease_ns, 15_000_000_000, 1)
            total(s, duration)
            if r < s:
                raise ControlError()
        except ControlError:
            raise DispatchError() from None
        with self._cv:
            if self._lease is not None:
                raise DispatchError("dispatch_busy")
            ticket = LeaseTicket(_KEY)
            self._lease = LeaseCell(ticket, s, r, duration)
            return ticket

    def take_lease_result(self, ticket):
        self._check()
        with self._cv:
            if (
                type(ticket) is not LeaseTicket
                or ticket not in _TICKETS
                or ticket._pid != self._pid
                or self._lease is None
                or self._lease.ticket is not ticket
            ):
                raise DispatchError("invalid_handle")
            result = self._lease.decision
            if result is not None:
                self._lease = None
            return result

    def _sample(self):
        try:
            value = integer(self._clock())
        except Exception:
            with self._cv:
                self._fault = "clock"
                self._stop_locked("clock")
                return self._current.last_ns
        with self._cv:
            # A caller may have sampled before the owner advanced control while
            # it was acquiring this lock. Only the serialized owner can compare
            # against C1A time; callers compare their own wait-start sample.
            if current_thread() is self._owner and value < self._current.last_ns:
                self._fault = "clock"
                self._stop_locked("clock")
        return value

    def _tick(self):
        now = self._sample()
        with self._cv:
            if self._stop_pending:
                reason, self._stop_pending = self._stop_pending, None
                self._current = self._control.request_stop(now_ns=now, reason=reason)
            else:
                self._current = self._control.tick(now_ns=now)

    def _lease_step(self):
        with self._cv:
            if self._lease is None or self._lease.decision is not None:
                return
        now = self._sample()
        with self._cv:
            cell = self._lease
            view = self._current
            bound = min(view.deadline_ns, cell.started + cell.duration - self._guard)
            accepted = (
                self._fault is None
                and not self._stop_pending
                and view.phase == "open"
                and not view.stop_requested
                and cell.started <= cell.received <= now
                and now < min(view.lease_ns, view.deadline_ns)
                and bound > view.lease_ns
            )
            if accepted:
                self._current = self._control.acknowledge_lease(
                    started_ns=cell.started, received_ns=now, remaining_lease_ns=cell.duration
                )
            else:
                # A fresh receipt check may itself discover expiry after the tick.
                self._current = self._control.tick(now_ns=now)
            cell.decision = LeaseDecision(
                accepted and self._current.phase == "open",
                self._current.lease_ns,
                self._copy_control(),
            )

    def _child_step(self):
        with self._cv:
            if not self._child:
                return
        now = self._sample()
        with self._cv:
            self._current = self._control.mark_child_closed(now_ns=now)
            self._child = False

    def _publication_step(self):
        with self._cv:
            if self._cell is None:
                return
        now = self._sample()
        with self._cv:
            # Stop intake and the reserve linearization share this lock.
            if self._stop_pending:
                reason, self._stop_pending = self._stop_pending, None
                self._current = self._control.request_stop(now_ns=now, reason=reason)
                return
            cell = self._cell
            if isinstance(cell, ReserveCell):
                if cell.state == "abandoned":
                    if cell.token is not None:
                        self._current = self._control.settle(
                            cell.token, outcome="rolled_back", now_ns=now
                        )
                        self._token, self._taken = None, False
                    self._cell = None
                elif cell.state == "requested":
                    token = None if self._fault else self._control.reserve(now_ns=now)
                    self._current = self._control.view()
                    cell.token = token
                    if token is not None:
                        self._token, self._taken = token, False
                    cell.state = "offered" if token is not None else "done"
            elif isinstance(cell, SettleCell) and not cell.done:
                try:
                    self._current = self._control.settle(
                        cell.token, outcome=cell.outcome, now_ns=now
                    )
                    cell.result = self._copy_control()
                except ControlError as error:
                    cell.error = error.code
                cell.done = True
            self._cv.notify_all()

    def step(self):
        self._check()
        owner = current_thread()
        with self._cv:
            if self._owner is not None and self._owner is not owner:
                raise DispatchError("wrong_owner")
        if not self._step_guard.acquire(blocking=False):
            raise DispatchError("dispatch_busy")
        try:
            with self._cv:
                if self._owner is None:
                    self._owner = owner
                elif self._owner is not owner:
                    raise DispatchError("wrong_owner")
            self._tick()
            self._lease_step()
            self._child_step()
            self._publication_step()
            return self.view()
        finally:
            self._step_guard.release()


def create_dispatcher(identity, budget, *, clock):
    try:
        if not callable(clock):
            raise ControlError()
        control = AttemptControl(identity, budget)
    except (ControlError, AttributeError, TypeError):
        raise DispatchError() from None
    obj = AttemptDispatcher(_KEY, control, clock)
    obj._guard = budget.guard_ns
    return obj
