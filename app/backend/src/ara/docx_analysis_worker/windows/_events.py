"""Unnamed monotonic events. Caller must remove a handle from waits before close."""

import os
import threading
from weakref import WeakSet

from ._errors import LocalResource, WindowsRuntimeError
from ._io_abi import _load_io

_ISSUE = object()
_EVENTS = WeakSet()


class NativeEvent(LocalResource):
    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("events are issued by create_event")
        return super().__new__(cls)

    def __init__(self, key, io, handle):
        if key is not _ISSUE or self in _EVENTS:
            raise TypeError("events are issued once")
        self._io, self._handle, self._pid = io, handle, os.getpid()
        self._mutex, self._failed = threading.Lock(), False
        _EVENTS.add(self)

    def _origin(self):
        if type(self) is not NativeEvent or self not in _EVENTS or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")

    def handle(self):
        self._origin()
        with self._mutex:
            if self._handle is None:
                raise WindowsRuntimeError("invalid_handle")
            return self._handle.value

    def set(self):
        self._origin()
        with self._mutex:
            if self._handle is None:
                raise WindowsRuntimeError("invalid_handle")
            try:
                self._io.set_event(self._handle.value)
            except Exception:
                raise WindowsRuntimeError("runtime_unavailable") from None

    def is_set(self):
        self._origin()
        with self._mutex:
            if self._handle is None:
                raise WindowsRuntimeError("invalid_handle")
            try:
                return self._io.wait_event(self._handle.value, 0)
            except Exception:
                raise WindowsRuntimeError("runtime_unavailable") from None

    def close(self):
        self._origin()
        with self._mutex:
            if self._failed:
                raise WindowsRuntimeError("runtime_unavailable")
            handle, self._handle = self._handle, None
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    self._failed = True
                    raise WindowsRuntimeError("runtime_unavailable") from None


def create_event():
    handle = None
    try:
        io = _load_io()
        handle = io.event()
        result = NativeEvent(_ISSUE, io, handle)
        handle = None
        return result
    except WindowsRuntimeError:
        raise
    except Exception:
        raise WindowsRuntimeError("runtime_unavailable") from None
    finally:
        if handle is not None:
            handle.close()
