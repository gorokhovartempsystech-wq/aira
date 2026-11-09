"""Strong, bounded retention of native buffers until actual IO completion."""

import ctypes as c
import os
import threading
from dataclasses import dataclass, field
from weakref import WeakSet

from ._errors import ClosedPipeError, LocalResource, WindowsRuntimeError
from ._io_abi import OVERLAPPED

_REGISTRY, _ISSUED = {}, WeakSet()
_MUTEX = threading.Lock()


@dataclass(frozen=True, slots=True)
class IOResult:
    kind: str
    count: int
    data: bytes = field(repr=False)
    eof: bool = False
    aborted: bool = False


class PendingIO(LocalResource):
    def __init__(self, owner, kind, data, size):
        self._owner, self._kind, self._size = owner, kind, size
        self._event = self._buffer = self._overlapped = None
        self._done, self._error, self._result = False, False, None
        self._cancelled, self._uncertain = False, False
        self._pid = os.getpid()
        with _MUTEX:
            if len(_REGISTRY) >= 64:
                raise WindowsRuntimeError("runtime_busy")
            _REGISTRY[id(self)] = self
            _ISSUED.add(self)
        try:
            self._buffer = (
                c.create_string_buffer(data, size)
                if data is not None
                else c.create_string_buffer(max(1, size))
            )
            self._event = owner._io.event()
            self._overlapped = OVERLAPPED(hEvent=self._event.value)
        except Exception:
            self._finish(error=True)
            raise WindowsRuntimeError("runtime_unavailable") from None

    def _check(self):
        if type(self) is not PendingIO or self not in _ISSUED or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")
        self._owner._origin()

    def event_handle(self):
        self._check()
        with self._owner._mutex:
            self._owner._thread()
            if self._done or self._event is None:
                raise WindowsRuntimeError("invalid_handle")
            return self._event.value

    def _finish(self, result=None, error=False):
        self._done, self._error, self._result = True, error, result
        event, self._event = self._event, None
        self._buffer = None
        try:
            if event is not None:
                event.close()
        except Exception:
            self._error, self._result = True, None
        finally:
            with _MUTEX:
                _REGISTRY.pop(id(self), None)
            if self._owner._operation is self:
                self._owner._operation = None

    def _start(self):
        io, handle = self._owner._io, self._owner._handle.value
        try:
            if self._kind == "connect":
                status = io.connect(handle, self._overlapped)
            else:
                status = getattr(io, self._kind)(handle, self._buffer, self._size, self._overlapped)
        except Exception:
            self._uncertain = True
            try:
                self._cancel()
            except Exception:
                pass
            raise WindowsRuntimeError("runtime_unavailable") from None
        if status == 535 and self._kind == "connect":
            try:
                io.set_event(self._event.value)
            except Exception:
                self._finish(error=True)
                raise WindowsRuntimeError("runtime_unavailable") from None
            self._finish(IOResult("connect", 0, b""))
        elif status == 109 and self._kind == "read":
            # A pipe can already be closed when ReadFile starts, not only at completion.
            self._finish(IOResult("read", 0, b"", eof=True))
        elif status in (109, 232, 233) and self._kind == "write":
            self._finish(IOResult("write", 0, b"", eof=True))
            self._poll()
        elif status not in (0, 997):
            self._finish(error=True)
            raise WindowsRuntimeError("runtime_unavailable")

    def _cancel(self):
        if self._done or self._cancelled:
            return
        self._cancelled = True
        try:
            self._owner._io.cancel(self._owner._handle.value, self._overlapped)
        except Exception:
            raise WindowsRuntimeError("runtime_unavailable") from None

    def cancel(self):
        self._check()
        with self._owner._mutex:
            self._cancel()

    def _poll(self):
        if not self._done:
            try:
                status, count = self._owner._io.result(self._owner._handle.value, self._overlapped)
            except Exception:
                # A failed completion query does not authorize freeing kernel memory.
                raise WindowsRuntimeError("runtime_unavailable") from None
            if status == 996:
                return None
            if status != 0 and self._overlapped.Internal == 0x103:
                raise WindowsRuntimeError("runtime_unavailable")
            error = self._uncertain
            if status == 995:
                result = IOResult(self._kind, 0, b"", aborted=True)
            elif status == 109 and self._kind == "read":
                result = IOResult("read", 0, b"", eof=True)
            elif status in (109, 232, 233) and self._kind == "write":
                result = IOResult("write", 0, b"", eof=True)
            elif status == 0 and self._kind == "connect":
                result = IOResult("connect", 0, b"")
            elif status == 0 and type(count) is int and 0 < count <= self._size:
                result = IOResult(
                    self._kind, count, self._buffer.raw[:count] if self._kind == "read" else b""
                )
            else:
                result, error = None, True
            self._finish(result, error)
        if self._error:
            raise WindowsRuntimeError("runtime_unavailable")
        if self._result.kind == "write" and self._result.eof:
            raise ClosedPipeError()
        return self._result

    def poll(self):
        self._check()
        with self._owner._mutex:
            self._owner._thread()
            return self._poll()


def reap_pending():
    """Explicit original IO-loop recovery, including failed setup records."""
    with _MUTEX:
        values = tuple(_REGISTRY.values())
    for op in values:
        op._check()
        if op._owner._io_thread != threading.get_ident():
            continue
        try:
            op.poll()
        except WindowsRuntimeError:
            pass
        if op._done and op._owner._orphaned:
            try:
                op._owner.close()
            except WindowsRuntimeError:
                pass
    with _MUTEX:
        return not _REGISTRY
