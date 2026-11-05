"""Invalidate before close; duplicates keep the same file object reservation alive."""

import os

from ._errors import LocalResource, WindowsRuntimeError


def valid_handle(value):
    return type(value) is int and 0 < value < 2**64 - 1


class OwnedHandle(LocalResource):
    __slots__ = ("_native", "_value", "_pid")

    def __init__(self, native, value):
        if not valid_handle(value):
            raise WindowsRuntimeError("runtime_unavailable")
        self._native, self._value, self._pid = native, value, os.getpid()

    @property
    def value(self):
        if not hasattr(self, "_pid") or self._pid != os.getpid() or self._value is None:
            raise WindowsRuntimeError("invalid_handle")
        return self._value

    def detach(self):
        value = self.value
        self._value = None
        return value

    def close(self):
        if not hasattr(self, "_pid") or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")
        value, self._value = self._value, None
        if value is not None:
            try:
                self._native.close(value)
            except Exception:
                raise WindowsRuntimeError("runtime_unavailable") from None

    def duplicate(self, inheritable=False):
        try:
            return OwnedHandle(self._native, self._native.duplicate(self.value, inheritable))
        except WindowsRuntimeError:
            raise
        except Exception:
            raise WindowsRuntimeError("runtime_unavailable") from None


def close_all(handles):
    failed = False
    for handle in reversed(handles):
        if handle is not None:
            try:
                handle.close()
            except Exception:
                failed = True
    if failed:
        raise WindowsRuntimeError("runtime_unavailable") from None


def duplicate_slot(slot):
    from ._locks import _SLOTS, RuntimeOwner, SlotLease

    if type(slot) is not SlotLease or slot not in _SLOTS or type(slot._owner) is not RuntimeOwner:
        raise WindowsRuntimeError("invalid_handle")
    owner = slot._owner
    owner._origin()
    with owner._mutex:
        owner._check_slot(slot)
        return slot._handle.duplicate(inheritable=True)
