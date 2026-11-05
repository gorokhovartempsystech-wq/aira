"""Issued unnamed Jobs; termination requests never imply an exit observation."""

import os
from weakref import WeakSet

from ._errors import LocalResource, WindowsRuntimeError
from ._handles import OwnedHandle
from ._process_abi import _load_api

_ISSUED = WeakSet()
_KEY = object()


class OwnedJob(LocalResource):
    def __init__(self, key, api, handle):
        if key is not _KEY:
            raise WindowsRuntimeError("invalid_handle")
        self.api, self._handle, self._pid = api, handle, os.getpid()
        self._terminated, self.fault = False, False
        self._close_failed = False
        _ISSUED.add(self)

    def handle(self):
        if type(self) is not OwnedJob or self not in _ISSUED or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")
        return self._handle.value

    def active_count(self):
        value = self.handle()
        try:
            result = self.api.job_count(value)
            if type(result) is not int or not 0 <= result < 2**32:
                raise ValueError()
            return result
        except Exception:
            self.fault = True
            raise WindowsRuntimeError("runtime_unavailable") from None

    def terminate(self):
        value = self.handle()
        if self._terminated:
            return
        self._terminated = True
        try:
            self.api.terminate_job(value)
        except Exception:
            self.fault = True
            raise WindowsRuntimeError("runtime_unavailable") from None

    def close(self):
        if self._pid != os.getpid() or self not in _ISSUED:
            raise WindowsRuntimeError("invalid_handle")
        if self._close_failed:
            raise WindowsRuntimeError("runtime_unavailable")
        try:
            self._handle.close()
        except Exception:
            self.fault = self._close_failed = True
            raise WindowsRuntimeError("runtime_unavailable") from None


def create_job(active_limit):
    if type(active_limit) is not int or active_limit not in (1, 2):
        raise WindowsRuntimeError("validation_error")
    handle = None
    try:
        api = _load_api()
        handle = OwnedHandle(api, api.new_job(active_limit))
        if api.job_limits(handle.value) != (0x2008, active_limit):
            raise ValueError()
        result = OwnedJob(_KEY, api, handle)
        handle = None
        return result
    except WindowsRuntimeError:
        raise
    except Exception:
        raise WindowsRuntimeError("runtime_unavailable") from None
    finally:
        if handle is not None:
            handle.close()
