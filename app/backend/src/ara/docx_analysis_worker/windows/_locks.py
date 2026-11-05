"""Separate owner and inherited execution reservations; no PID or unlock files."""

import ctypes
import os
import sys
import threading
from weakref import WeakSet

from . import _paths
from ._errors import LocalResource, WindowsRuntimeError
from ._handles import close_all

_ISSUE = object()
_OWNERS, _SLOTS = WeakSet(), WeakSet()


def _safe(call):
    try:
        return call()
    except WindowsRuntimeError:
        raise
    except Exception:
        raise WindowsRuntimeError("runtime_unavailable") from None


class SlotLease(LocalResource):
    __slots__ = ("_owner", "_handle", "_identity")

    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("slots are issued by an owner")
        return super().__new__(cls)

    def __init__(self, key, owner, handle, identity):
        if key is not _ISSUE or self in _SLOTS:
            raise TypeError("slots are issued once")
        self._owner, self._handle, self._identity = owner, handle, identity
        _SLOTS.add(self)

    def handle(self):
        if type(self) is not SlotLease or self not in _SLOTS:
            raise WindowsRuntimeError("invalid_handle")
        owner = self._owner
        if type(owner) is not RuntimeOwner:
            raise WindowsRuntimeError("invalid_handle")
        owner._origin()
        with owner._mutex:
            owner._check_slot(self)
            return self._handle.value


class RuntimeOwner(LocalResource):
    __slots__ = (
        "_fs",
        "_pins",
        "_handle",
        "_identity",
        "_sid",
        "_pid",
        "_slot",
        "_slot_id",
        "_mutex",
    )

    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("owners are issued by acquire_owner")
        return super().__new__(cls)

    def __init__(self, key, fs, pins, handle, identity, sid):
        if key is not _ISSUE or self in _OWNERS:
            raise TypeError("owners are issued once")
        self._fs, self._pins, self._handle, self._identity, self._sid = (
            fs,
            pins,
            handle,
            identity,
            sid,
        )
        self._pid, self._slot, self._slot_id = os.getpid(), None, None
        self._mutex = threading.Lock()
        _OWNERS.add(self)

    def _origin(self):
        if type(self) is not RuntimeOwner or self not in _OWNERS or self._pid != os.getpid():
            raise WindowsRuntimeError("invalid_handle")

    def _live(self):
        if self._handle is None:
            raise WindowsRuntimeError("invalid_handle")

    def _check_slot(self, slot):
        self._live()
        if (
            type(slot) is not SlotLease
            or slot not in _SLOTS
            or slot is not self._slot
            or slot._handle is None
        ):
            raise WindowsRuntimeError("invalid_handle")

    def _path(self, name):
        return self._pins[-1][0] + "\\" + name

    def _check_file(self, handle, name, identity=None):
        return _paths.check_info(
            self._fs,
            handle,
            self._path(name),
            directory=False,
            sid=self._sid,
            volume=self._pins[-1][2][0],
            identity=identity,
        )

    def _recheck(self):
        _paths.recheck_root(self._fs, self._pins, self._sid)
        self._check_file(self._handle, "runtime.owner", self._identity)

    def _open_slot(self, create):
        handle = None
        try:
            self._recheck()
            handle = self._fs.file(self._path("analysis.slot"), create, self._sid)
            identity = self._check_file(handle, "analysis.slot", self._slot_id)
            self._recheck()
            result, handle = handle, None
            return result, identity
        finally:
            close_all([handle])

    def reserve_slot(self):
        self._origin()
        with self._mutex:
            self._live()
            if self._slot is not None:
                raise WindowsRuntimeError("runtime_busy")

            def reserve():
                handle, identity = self._open_slot(self._slot_id is None)
                try:
                    slot = SlotLease(_ISSUE, self, handle, identity)
                except Exception:
                    handle.close()
                    raise
                self._slot, self._slot_id = slot, identity
                return slot

            return _safe(reserve)

    def release_slot(self, slot):
        self._origin()
        with self._mutex:
            self._check_slot(slot)

            def release():
                self._recheck()
                self._check_file(slot._handle, "analysis.slot", slot._identity)
                handle, slot._handle, self._slot = slot._handle, None, None
                handle.close()
                try:
                    probe, _ = self._open_slot(False)
                except WindowsRuntimeError as error:
                    if error.code == "runtime_busy":
                        return False
                    raise
                probe.close()
                return True

            return _safe(release)

    def _close(self):
        handles = [item[1] for item in self._pins] + [self._handle]
        if self._slot is not None:
            handles.append(self._slot._handle)
            self._slot._handle, self._slot = None, None
        self._pins, self._handle = [], None
        close_all(handles)

    def close(self):
        self._origin()
        with self._mutex:
            if self._slot is not None:
                raise WindowsRuntimeError("runtime_busy")
            self._close()

    def abandon(self):
        self._origin()
        with self._mutex:
            self._close()


def acquire_owner(root):
    paths = _paths.root_parts(root)
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise WindowsRuntimeError("platform_unavailable")

    def acquire():
        fs = _paths._load_filesystem()
        sid = fs.user()
        pins, handle = [], None
        try:
            pins = _paths.pin_root(fs, paths, sid)
            handle = fs.file(root + "\\runtime.owner", True, sid)
            identity = _paths.check_info(
                fs,
                handle,
                root + "\\runtime.owner",
                directory=False,
                sid=sid,
                volume=pins[-1][2][0],
            )
            _paths.recheck_root(fs, pins, sid)
            owner = RuntimeOwner(_ISSUE, fs, pins, handle, identity, sid)
            pins, handle = [], None
            return owner
        finally:
            close_all([item[1] for item in pins] + [handle])

    return _safe(acquire)
