"""Single loop owns an unreaped direct child. No PID adoption or Popen polling."""

import errno
import os
import select
import signal
from subprocess import Popen

from ._errors import LocalResource, MacRuntimeError


class OwnedChild(LocalResource):
    def __init__(self, process):
        if not isinstance(process, Popen) or process.returncode is not None:
            raise MacRuntimeError("invalid_handle")
        self._process, self._pid = process, process.pid
        self._origin = os.getpid()
        self._signals = True
        self._stop_at = None
        self._exited = self._lost = self._hard_fault = self._signal_error = False
        self._signal_errno = None
        self._exit_code = None
        self._queue = None
        try:
            self._queue = select.kqueue()
            self._queue.control(
                [
                    select.kevent(
                        self._pid,
                        filter=select.KQ_FILTER_PROC,
                        flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                        fflags=select.KQ_NOTE_EXIT,
                    )
                ],
                0,
                0,
            )
        except Exception:
            self._hard_fault = True

    @property
    def exited(self):
        return self._exited

    @property
    def lost(self):
        return self._lost

    @property
    def exit_code(self):
        return self._exit_code

    @property
    def signal_error(self):
        return self._signal_error

    @property
    def signal_errno(self):
        return self._signal_errno

    @property
    def hard_fault(self):
        return self._hard_fault

    @property
    def fault(self):
        return self._signal_error or self._hard_fault or self._lost

    def _observe(self):
        if self._queue is None or self.hard_fault:
            return False
        try:
            for event in self._queue.control(None, 1, 0):
                if event.flags & select.KQ_EV_ERROR:
                    self._hard_fault = True
                elif (
                    event.ident == self._pid
                    and event.filter == select.KQ_FILTER_PROC
                    and event.fflags & select.KQ_NOTE_EXIT
                ):
                    self._signals = False
                    return True
        except Exception:
            self._hard_fault = True
        return False

    def _signal(self, number):
        try:
            if type(number) not in (int, signal.Signals) or number not in (
                signal.SIGTERM,
                signal.SIGKILL,
            ):
                raise ValueError()
            os.killpg(self._pid, number)
        except Exception as error:
            self._signal_error, self._signals = True, False
            self._signal_errno = {
                errno.EPERM: "eperm",
                errno.ESRCH: "esrch",
                errno.EINTR: "eintr",
            }.get(error.errno if isinstance(error, OSError) else None, "unexpected")
            if self._signal_errno == "unexpected":
                self._hard_fault = True

    def _poll(self, now_ns, stop=False, force=False):
        self._check_origin()
        if self.exited or self.lost:
            return
        if self._signals:
            self._observe()
        if self._signals:
            if force or self.hard_fault:
                self._signal(signal.SIGKILL)
                self._signals = False
            elif stop and self._stop_at is None:
                self._stop_at = now_ns
                self._signal(signal.SIGTERM)
            elif self._stop_at is not None and now_ns >= self._stop_at + 2_000_000_000:
                self._signal(signal.SIGKILL)
                self._signals = False
        if not self._signals:
            try:
                pid, status = os.waitpid(self._pid, os.WNOHANG)
                if pid == 0:
                    return
                if pid != self._pid or not (os.WIFEXITED(status) or os.WIFSIGNALED(status)):
                    raise ChildProcessError()
                self._exit_code = os.waitstatus_to_exitcode(status)
                self._process.returncode = self.exit_code
                self._exited = True
            except Exception:
                self._lost = self._hard_fault = True

    def close(self):
        self._check_origin()
        if self._signals:
            raise MacRuntimeError("runtime_busy")
        queue, self._queue = self._queue, None
        if queue is not None:
            queue.close()

    def _check_origin(self):
        if not hasattr(self, "_origin") or self._origin != os.getpid():
            raise MacRuntimeError("invalid_handle")
