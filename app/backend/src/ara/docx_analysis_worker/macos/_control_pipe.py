"""Small atomic control writes never take the data/decoder mutex."""

import os
import threading

from ..wire import encode_message
from ..wire._codec import binding_copy
from ._errors import MacRuntimeError

REASONS = frozenset(("user", "deadline", "lease", "storage", "shutdown", "protocol"))


class ControlPipe:
    def __init__(self, holder, binding, budget, clock):
        self._holder, self._binding, self._clock = holder, binding_copy(binding), clock
        self._deadline, self._lease, self._last = (
            budget.deadline_ns,
            budget.lease_ns,
            budget.last_ns,
        )
        self._lock = threading.Lock()
        self._closed = self._stopped = False
        self._error = None
        self._seq = self._total = 0
        try:
            self._atomic = os.fpathconf(holder.control_fd, "PC_PIPE_BUF")
            with self._lock:
                if not self._check_time():
                    raise MacRuntimeError("runtime_unavailable")
                self._send(
                    "permit", dict(deadline_ns=str(self._deadline), lease_ns=str(self._lease))
                )
        except Exception:
            self._fail("transport")
            raise MacRuntimeError("runtime_unavailable") from None

    @property
    def stop_requested(self):
        return self.flags()[0]

    @property
    def error_code(self):
        return self.flags()[1]

    def flags(self):
        with self._lock:
            return self._stopped, self._error, self._deadline, self._lease

    def _close(self):
        if not self._closed:
            self._closed = True
            try:
                self._holder.close_control()
            except Exception:
                if self._error is None:
                    self._error = "transport"
                self._stopped = True

    def _fail(self, code):
        if self._error is None:
            self._error = code
        self._stopped = True
        self._close()

    def abort(self, code):
        if code not in (
            "clock",
            "lease",
            "deadline",
            "protocol",
            "process",
            "transport",
            "shutdown_timeout",
        ):
            code = "transport"
        with self._lock:
            self._fail(code)

    def _check_time(self):
        if self._stopped:
            return False
        try:
            now = self._clock.now_ns()
            if type(now) is not int or not self._last <= now <= 2**63 - 1:
                raise ValueError()
        except Exception:
            self._fail("clock")
            return False
        self._last = now
        if now >= self._deadline:
            self._fail("deadline")
        elif now >= self._lease:
            self._fail("lease")
        return not self._stopped

    def check(self):
        with self._lock:
            return self._check_time()

    def _send(self, kind, values):
        try:
            raw = encode_message(self._binding, kind=kind, seq=self._seq, values=values)
            if (
                len(raw) > self._atomic
                or self._seq >= 512
                or self._total + len(raw) - 4 > 1024 * 1024
            ):
                raise ValueError()
            if os.write(self._holder.control_fd, raw) != len(raw):
                raise OSError()
        except Exception:
            self._fail("transport")
            raise MacRuntimeError("runtime_unavailable") from None
        self._seq += 1
        self._total += len(raw) - 4

    def renew(self, lease_ns):
        if type(lease_ns) is not int or not 0 < lease_ns <= self._deadline:
            raise MacRuntimeError("validation_error")
        with self._lock:
            if self._closed or self._stopped:
                return False
            if not self._check_time():
                raise MacRuntimeError("runtime_unavailable")
            if lease_ns <= self._last or lease_ns - self._last > 15_000_000_000:
                raise MacRuntimeError("validation_error")
            self._send("permit", dict(deadline_ns=str(self._deadline), lease_ns=str(lease_ns)))
            self._lease = lease_ns
            return True

    def stop(self, reason="user"):
        if type(reason) is not str or reason not in REASONS:
            raise MacRuntimeError("validation_error")
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            if reason == "protocol" and self._error is None:
                self._error = "protocol"
            if not self._closed:
                try:
                    self._send("stop", dict(reason=reason))
                except MacRuntimeError:
                    pass
                self._close()

    def finish(self):
        with self._lock:
            self._close()
