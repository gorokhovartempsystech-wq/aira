"""Darwin continuous time includes sleep; native loading is explicit and lazy."""

import os
import sys
import threading

from ._errors import LocalResource, MacRuntimeError


def ticks_to_ns(ticks, numer, denom):
    if not (
        type(ticks) is int
        and 0 <= ticks <= 2**64 - 1
        and type(numer) is int
        and 1 <= numer <= 2**32 - 1
        and type(denom) is int
        and 1 <= denom <= 2**32 - 1
    ):
        raise MacRuntimeError("validation_error")
    value = ticks * numer // denom
    if value > 2**63 - 1:
        raise MacRuntimeError("clock_unavailable")
    return value


def _load_clock():
    import ctypes

    class Timebase(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

    library = ctypes.CDLL(None)
    library.mach_continuous_time.argtypes = []
    library.mach_continuous_time.restype = ctypes.c_uint64
    library.mach_timebase_info.argtypes = [ctypes.POINTER(Timebase)]
    library.mach_timebase_info.restype = ctypes.c_int
    info = Timebase()
    if library.mach_timebase_info(ctypes.byref(info)) != 0 or not info.numer or not info.denom:
        raise MacRuntimeError("clock_unavailable")
    return library.mach_continuous_time, int(info.numer), int(info.denom)


class DarwinClock(LocalResource):
    __slots__ = ("_lock", "_pid", "_native", "_last", "_failed")

    def __init__(self):
        self._lock = threading.Lock()
        self._pid = None
        self._native = None
        self._last = None
        self._failed = False

    def now_ns(self):
        # Check before acquiring an inherited mutex: it may have been locked at fork.
        if not hasattr(self, "_pid") or (self._pid is not None and self._pid != os.getpid()):
            raise MacRuntimeError("invalid_handle")
        with self._lock:
            if self._failed:
                raise MacRuntimeError("clock_unavailable")
            if sys.platform != "darwin":
                raise MacRuntimeError("platform_unavailable")
            if self._pid is None:
                self._pid = os.getpid()
            try:
                if self._native is None:
                    self._native = _load_clock()
                read, numer, denom = self._native
                value = ticks_to_ns(read(), numer, denom)
                if self._last is not None and value < self._last:
                    raise MacRuntimeError("clock_unavailable")
            except Exception:
                self._failed = True
                raise MacRuntimeError("clock_unavailable") from None
            self._last = value
            return value
