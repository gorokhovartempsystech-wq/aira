"""Explicit fixture holder, retained before any OS setup. No SQL or production wiring."""

import os
import threading
from dataclasses import dataclass
from uuid import UUID
from weakref import WeakSet

from ..wire import WireBinding
from ._adopt import MODES, launch_config
from ._clock import WindowsClock
from ._errors import LocalResource, WindowsRuntimeError
from ._events import create_event
from ._handles import duplicate_slot
from ._jobs import create_job
from ._locks import _SLOTS, SlotLease
from ._pending import reap_pending
from ._pipes import create_pipe_pair
from ._spawn import SpawnRecord

_REGISTRY, _ISSUED = {}, WeakSet()
_MUTEX, _KEY = threading.Lock(), object()


@dataclass(frozen=True, slots=True)
class Channels:
    control: object
    request: object
    events: object
    status: object
    armed: object


@dataclass(frozen=True, slots=True)
class LaunchObservation:
    creation: str
    process_exited: bool
    exit_code: int | None
    job_empty: bool
    resources_closed: bool
    hard_fault: bool


class FixtureLaunch(LocalResource):
    def __init__(self, key, slot, binding, deadline, lease, mode):
        if key is not _KEY:
            raise WindowsRuntimeError("invalid_handle")
        self._slot, self._binding, self._d, self._l, self._mode = (
            slot,
            binding,
            deadline,
            lease,
            mode,
        )
        self._pid, self._thread, self._clock, self._last = os.getpid(), None, WindowsClock(), None
        self._mutex = threading.Lock()
        self._r = self._h = self._closed = self._started = self._ready = False
        self._stop_at = self._job = self._record = self._channels = None
        self._pairs, self._locals, self._signals = [], [], []
        self._close_failed = False
        self._exited_at = None
        with _MUTEX:
            if _REGISTRY:
                raise WindowsRuntimeError("runtime_busy")
            _REGISTRY[id(self)] = self
            _ISSUED.add(self)

    def _check(self, owner=False):
        if type(self) is not FixtureLaunch or self not in _ISSUED or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")
        if owner:
            if self._thread is None:
                self._thread = threading.get_ident()
            if self._thread != threading.get_ident():
                raise WindowsRuntimeError("invalid_handle")

    def _now(self):
        try:
            value = self._clock.now_ns()
        except Exception:
            self._h = True
            raise WindowsRuntimeError("clock_unavailable") from None
        if (
            type(value) is not int
            or not 0 <= value < 2**63
            or self._last is not None
            and value < self._last
        ):
            self._h = True
            raise WindowsRuntimeError("runtime_unavailable")
        self._last = value
        return value

    def _live(self):
        now = self._now()
        with self._mutex:
            return not self._r and not self._h and now < min(self._d, self._l)

    def request_stop(self, *, hard=False):
        self._check()
        if type(hard) is not bool:
            raise WindowsRuntimeError("validation_error")
        with self._mutex:
            self._r, self._h = True, self._h or hard
            if self._closed:
                return
            if len(self._signals) > (1 if self._h else 0):
                try:
                    self._signals[1 if self._h else 0].set()
                except Exception:
                    self._h = True
                    raise WindowsRuntimeError("runtime_unavailable") from None

    @property
    def channels(self):
        self._check()
        if not self._ready or self._closed:
            raise WindowsRuntimeError("invalid_handle")
        return self._channels

    def start(self):
        self._check(True)
        if self._started or self._closed:
            raise WindowsRuntimeError("invalid_handle")
        self._started = True
        try:
            if not self._live():
                raise ValueError()
            now = self._now()
            if self._d > now + 300_000_000_000 or self._l > now + 15_000_000_000:
                raise ValueError()
            for _ in range(5):
                self._pairs.append(
                    create_pipe_pair(deadline_ns=min(self._l, self._d), clock=self._clock)
                )
            control, status, armed, request, events = self._pairs
            for _ in range(2):
                event = create_event()
                with self._mutex:
                    self._signals.append(event)
            with self._mutex:
                if self._r or self._h:
                    self._signals[1 if self._h else 0].set()
            self._job = create_job(2)
            api = self._job.api
            self._locals.append(api.nul())
            self._locals.append(api.nul(True))
            self._locals.append(duplicate_slot(self._slot))
            api.clear_inherit(self._locals[2].value)
            roles = {
                "control": control.reader.handle(),
                "status": status.writer.handle(),
                "armed": armed.writer.handle(),
                "request": request.reader.handle(),
                "events": events.writer.handle(),
                "slot": self._locals[2].value,
                "ordinary": self._signals[0].handle(),
                "hard": self._signals[1].handle(),
                "stdin": self._locals[0].value,
                "stdout": self._locals[1].value,
            }
            self._record = SpawnRecord(api, self._job)
            if not self._live():
                raise ValueError()
            self._record.create(
                lambda h: launch_config("G", self._binding, self._d, self._l, self._mode, h, api),
                roles,
                ("stdin", "stdout", "stdout"),
            )
            self._record.resume(self._live)
            for endpoint in (
                control.reader,
                status.writer,
                armed.writer,
                request.reader,
                events.writer,
            ):
                if not endpoint.close():
                    raise ValueError()
            self._channels = Channels(
                control.writer, request.writer, events.reader, status.reader, armed.reader
            )
            self._ready = True
        except Exception:
            self._h = self._h or not self._r or bool(self._record and self._record.fault)
            if self._record is not None:
                self._record.terminate()
            raise WindowsRuntimeError("runtime_unavailable") from None
        finally:
            for handle in self._locals:
                try:
                    handle.close()
                except Exception:
                    self._h = self._close_failed = True
            self._locals.clear()
        if self._close_failed:
            self._ready = False
            if self._record is not None:
                self._record.terminate()
            raise WindowsRuntimeError("runtime_unavailable")

    def poll_process(self):
        self._check(True)
        if not self._closed:
            try:
                now = self._now() if self._started else None
                if now is not None and now >= self._d:
                    self.request_stop()
                if self._r and self._stop_at is None:
                    self._stop_at = now
                if self._record is not None:
                    self._record.poll()
                    count = self._job.active_count()
                    if self._record.exited and count:
                        if self._exited_at is None:
                            self._exited_at = now
                        if now is None or now - self._exited_at >= 2_000_000_000:
                            self._h = True
                    if (
                        self._h
                        or self._r
                        and now is not None
                        and now - self._stop_at >= 5_000_000_000
                    ):
                        self._record.terminate()
            except Exception:
                self._h = True
                if self._record is not None:
                    self._record.terminate()
        record = self._record
        empty = False
        try:
            empty = self._job is None or self._closed or self._job.active_count() == 0
        except Exception:
            self._h = True
        return LaunchObservation(
            record.creation if record else "not_started",
            bool(record and record.exited),
            record.exit_code if record else None,
            empty,
            self._closed,
            self._h or bool(record and record.fault),
        )

    def finish_close(self):
        self._check(True)
        if self._closed:
            return True
        if self._close_failed:
            return False
        observation = self.poll_process()
        if self._record is not None and (
            self._record.creation == "unknown"
            or self._record.creation == "created"
            and not observation.process_exited
        ):
            return False
        if not observation.job_empty:
            return False
        complete = reap_pending()
        for pair in self._pairs:
            for endpoint in (pair.reader, pair.writer):
                with endpoint._mutex:
                    foreign = endpoint._io_thread not in (None, threading.get_ident())
                    closed = (
                        endpoint._handle is None
                        and endpoint._operation is None
                        and not endpoint._close_failed
                    )
                if foreign:
                    complete = closed and complete
                else:
                    try:
                        complete = endpoint.close() and complete
                    except Exception:
                        self._h = self._close_failed = True
                        complete = False
        if not complete:
            return False
        if self._record is not None and not self._record.close():
            return False
        try:
            if self._job is not None:
                self._job.close()
            with self._mutex:
                for event in self._signals:
                    event.close()
                self._closed = True
        except Exception:
            self._h = self._close_failed = True
            return False
        with _MUTEX:
            _REGISTRY.pop(id(self), None)
        self._slot = None
        return True


def prepare_fixture_guardian(slot, binding, *, deadline_ns, lease_ns, mode="success"):
    if (
        type(slot) is not SlotLease
        or slot not in _SLOTS
        or type(binding) is not WireBinding
        or type(binding.run_id) is not UUID
        or type(binding.attempt_id) is not UUID
        or type(deadline_ns) is not int
        or type(lease_ns) is not int
        or not 0 < lease_ns <= deadline_ns < 2**63
        or type(mode) is not str
        or mode not in MODES
    ):
        raise WindowsRuntimeError("validation_error")
    slot.handle()
    return FixtureLaunch(
        _KEY, slot, WireBinding(binding.run_id, binding.attempt_id), deadline_ns, lease_ns, mode
    )
