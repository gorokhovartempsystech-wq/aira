"""One-shot connected private pipe pairs, with explicit bounded async lifetime."""

import os
import threading
import uuid
from weakref import WeakSet

from ._errors import LocalResource, WindowsRuntimeError
from ._io_abi import _load_io
from ._pending import PendingIO

_ENDPOINTS, _PAIRS = WeakSet(), WeakSet()
_ISSUE = object()


class PipeEndpoint(LocalResource):
    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("endpoints are issued by pipe setup")
        return super().__new__(cls)

    def __init__(self, key, io, handle, kind, synchronous=False):
        if key is not _ISSUE or self in _ENDPOINTS:
            raise TypeError("endpoints issued once")
        self._io, self._handle, self._kind, self._synchronous = io, handle, kind, synchronous
        self._pid, self._io_thread = os.getpid(), None
        self._mutex = threading.Lock()
        self._operation, self._close_failed = None, False
        self._orphaned = False
        _ENDPOINTS.add(self)

    def _origin(self):
        if type(self) is not PipeEndpoint or self not in _ENDPOINTS or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")

    def _thread(self):
        if self._io_thread is not None and self._io_thread != threading.get_ident():
            raise WindowsRuntimeError("invalid_handle")

    def handle(self):
        self._origin()
        with self._mutex:
            if self._handle is None:
                raise WindowsRuntimeError("invalid_handle")
            return self._handle.value

    def _begin(self, kind, data, size):
        self._origin()
        with self._mutex:
            self._thread()
            if (
                self._handle is None
                or self._synchronous
                or (kind != "connect" and kind != self._kind)
            ):
                raise WindowsRuntimeError("invalid_handle")
            if self._operation is not None:
                raise WindowsRuntimeError("runtime_busy")
            self._io_thread = threading.get_ident()
            op = PendingIO(self, kind, data, size)
            self._operation = op
            op._start()
            return op

    def begin_read(self, size=65536):
        if type(size) is not int or not 1 <= size <= 65536:
            raise WindowsRuntimeError("validation_error")
        return self._begin("read", None, size)

    def begin_write(self, data):
        if type(data) is not bytes or not 1 <= len(data) <= 65536:
            raise WindowsRuntimeError("validation_error")
        return self._begin("write", data, len(data))

    def close(self):
        self._origin()
        with self._mutex:
            if self._close_failed:
                raise WindowsRuntimeError("runtime_unavailable")
            if self._handle is None:
                return True
            self._thread()
            error = False
            if self._operation is not None:
                op = self._operation
                op._cancel()
                try:
                    if op._poll() is None:
                        return False
                except WindowsRuntimeError:
                    if not op._done:
                        raise
                    error = True
            handle, self._handle = self._handle, None
            try:
                handle.close()
            except Exception:
                self._close_failed = True
                raise WindowsRuntimeError("runtime_unavailable") from None
            if error:
                raise WindowsRuntimeError("runtime_unavailable")
            return True


class PipePair(LocalResource):
    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("pairs are issued by setup")
        return super().__new__(cls)

    def __init__(self, key, reader, writer):
        if key is not _ISSUE or self in _PAIRS:
            raise TypeError("pairs issued once")
        self._reader, self._writer, self._pid = reader, writer, os.getpid()
        _PAIRS.add(self)

    def _check(self):
        if type(self) is not PipePair or self not in _PAIRS or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")

    @property
    def reader(self):
        self._check()
        return self._reader

    @property
    def writer(self):
        self._check()
        return self._writer

    def close(self):
        self._check()
        result, error = True, False
        for endpoint in (self._writer, self._reader):
            try:
                result = endpoint.close() and result
            except Exception:
                error = True
        if error:
            raise WindowsRuntimeError("runtime_unavailable") from None
        return result


def create_pipe_pair(*, deadline_ns, clock, synchronous_writer=False):
    if (
        type(deadline_ns) is not int
        or not 0 <= deadline_ns < 2**63
        or type(synchronous_writer) is not bool
    ):
        raise WindowsRuntimeError("validation_error")
    reader = writer = raw = None
    last = None

    def now():
        nonlocal last
        value = clock.now_ns()
        if type(value) is not int or not 0 <= value < 2**63 or (last is not None and value < last):
            raise WindowsRuntimeError("runtime_unavailable")
        last = value
        return value

    try:
        cutoff = min(deadline_ns, now() + 2_000_000_000)

        def check():
            if now() >= cutoff:
                raise WindowsRuntimeError("runtime_unavailable")

        check()
        io = _load_io()
        sid = io.user()
        name = "\\\\.\\pipe\\aira-" + uuid.uuid4().hex
        check()
        raw = io.server(name, sid)
        reader = PipeEndpoint(_ISSUE, io, raw, "read")
        raw = None
        check()
        connect = reader._begin("connect", None, 0)
        check()
        raw = io.client(name, synchronous_writer)
        writer = PipeEndpoint(_ISSUE, io, raw, "write", synchronous_writer)
        raw = None
        while True:
            check()
            result = connect.poll()
            if result is not None:
                if result.aborted or result.eof:
                    raise WindowsRuntimeError("runtime_unavailable")
                break
            io.wait_event(connect.event_handle(), max(1, min(100, (cutoff - now()) // 1_000_000)))
        check()
        if io.peer_processes(reader.handle(), writer.handle()) != (io.pid(), io.pid()):
            raise WindowsRuntimeError("runtime_unavailable")
        reader._io_thread = None
        pair = PipePair(_ISSUE, reader, writer)
        reader = writer = None
        return pair
    except WindowsRuntimeError:
        raise
    except Exception:
        raise WindowsRuntimeError("runtime_unavailable") from None
    finally:
        for endpoint in (writer, reader):
            if endpoint is not None:
                endpoint._orphaned = True
                try:
                    endpoint.close()
                except Exception:
                    pass  # Pending registry retains ownership; never false cleanup ACK.
        if raw is not None:
            raw.close()
