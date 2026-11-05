"""Synchronous C1B adapter with offered/taken grants and retained settlements."""

from threading import current_thread

from ara.docx_analysis_runs.guarded_port import PublicationPort, publication_fail

from ..control import CommitPermit, ControlError
from ..control._controller import OUTCOMES
from ..control._models import Uncopyable
from ._dispatch_cells import ReserveCell, SettleCell, WaitBudget
from ._dispatch_models import _KEY, DispatchError


class DispatcherPublicationPort(PublicationPort, Uncopyable):
    def __init__(self, key, dispatcher):
        if key is not _KEY or hasattr(self, "_dispatcher"):
            raise TypeError("ports are issued once by a dispatcher")
        self._dispatcher = dispatcher

    def __repr__(self):
        return "<DispatcherPublicationPort>"

    def _check(self):
        from .dispatcher import AttemptDispatcher

        d = getattr(self, "_dispatcher", None)
        if type(d) is not AttemptDispatcher:
            raise DispatchError("invalid_handle")
        d._check()
        if type(self) is not DispatcherPublicationPort or d._port is not self:
            raise DispatchError("invalid_handle")
        return d

    def view(self):
        return self._check().view().control

    def _enter(self):
        d = self._check()
        with d._cv:
            if d._owner is current_thread():
                raise DispatchError("dispatch_busy")
        if not d._caller_guard.acquire(blocking=False):
            publication_fail("publication_in_progress")
        return d

    def reserve(self):
        d = self._enter()
        try:
            now = d._sample()
            wait = WaitBudget(now)
            with d._cv:
                if d._cell is not None:
                    publication_fail("publication_in_progress")
                if d._fault or now >= min(d._current.deadline_ns, d._current.lease_ns):
                    return None
                cell = ReserveCell()
                d._cell = cell
                d._cv.notify_all()
            while True:
                now = d._sample()
                with d._cv:
                    if cell.state == "done":
                        d._cell = None
                        return None
                    # A fresh reading after acquiring the lock gates delivery.
                    if cell.state == "offered":
                        now = d._sample()
                    remaining = wait.remaining(now)
                    if now < wait.start:
                        d._fault = "clock"
                        d._stop_locked("clock")
                    expired = now >= min(d._current.deadline_ns, d._current.lease_ns)
                    if d._fault or remaining <= 0 or now < wait.start or expired:
                        cell.state = "abandoned"
                        d._cv.notify_all()
                        return None
                    if cell.state == "offered":
                        cell.state = "taken"
                        d._taken = True
                        d._cell = None
                        return cell.token
                    d._cv.wait(remaining / 1_000_000_000)
        finally:
            d._caller_guard.release()

    def settle(self, permit, *, outcome):
        d = self._enter()
        try:
            if type(outcome) is not str or outcome not in OUTCOMES:
                raise ControlError()
            now = d._sample()
            wait = WaitBudget(now)
            with d._cv:
                if type(permit) is not CommitPermit or permit is not d._token or not d._taken:
                    raise ControlError("invalid_permit")
                cell = d._cell
                if cell is not None:
                    if (
                        not isinstance(cell, SettleCell)
                        or cell.token is not permit
                        or cell.outcome != outcome
                    ):
                        publication_fail("publication_in_progress")
                else:
                    cell = SettleCell(permit, outcome)
                    d._cell = cell
                    d._cv.notify_all()
            while True:
                now = d._sample()
                with d._cv:
                    if now < wait.start:
                        d._fault = "clock"
                        d._stop_locked("clock")
                    remaining = wait.remaining(now)
                    if remaining <= 0:
                        publication_fail("publication_in_progress")
                    if cell.done:
                        d._cell = None
                        if cell.error:
                            raise ControlError(cell.error)
                        return cell.result
                    d._cv.wait(remaining / 1_000_000_000)
        finally:
            d._caller_guard.release()
