"""Explicit lazy Windows sleep-inclusive clock. No implicit native initialization."""

import ctypes
import os
import sys
import threading

from ._errors import LocalResource, WindowsRuntimeError


def milliseconds_to_ns(milliseconds):
    if type(milliseconds) is not int or not 0 <= milliseconds < 2**64:
        raise WindowsRuntimeError("validation_error")
    result = milliseconds * 1_000_000
    if result >= 2**63:
        raise WindowsRuntimeError("clock_unavailable")
    return result


def _load_clock():
    from ._abi import DWORD64, library

    kernel = library("kernel32.dll")
    read = kernel.GetTickCount64
    read.argtypes, read.restype = [], DWORD64
    return read


class WindowsClock(LocalResource):
    __slots__ = ("_mutex", "_pid", "_read", "_last", "_failed")

    def __init__(self):
        self._mutex = threading.Lock()
        self._pid = self._read = self._last = None
        self._failed = False

    def now_ns(self):
        if not hasattr(self, "_pid") or self._pid not in (None, os.getpid()):
            raise WindowsRuntimeError("invalid_handle")
        with self._mutex:
            if self._failed:
                raise WindowsRuntimeError("clock_unavailable")
            if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
                raise WindowsRuntimeError("platform_unavailable")
            self._pid = os.getpid()
            try:
                if self._read is None:
                    self._read = _load_clock()
                value = milliseconds_to_ns(self._read())
                if self._last is not None and value < self._last:
                    raise WindowsRuntimeError("clock_unavailable")
            except Exception:
                self._failed = True
                raise WindowsRuntimeError("clock_unavailable") from None
            self._last = value
            return value
