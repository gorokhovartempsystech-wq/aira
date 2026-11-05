"""Owner then slot; shared lock descriptions are closed, never explicitly unlocked."""

import errno
import os
import stat
import sys
import threading
from pathlib import Path
from weakref import WeakSet

from ._errors import LocalResource, MacRuntimeError

_ISSUE = object()
_OWNERS = WeakSet()
_SLOTS = WeakSet()


def _close_all(fds):
    failed = False
    for fd in fds:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                failed = True
    if failed:
        raise MacRuntimeError("runtime_unavailable") from None


def _identity(info):
    return info.st_dev, info.st_ino


def _directory(root):
    """Return a retained verified root FD; never resolve an untrusted symlink."""
    fd = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open("/", flags)
        for part in root.parts[1:]:
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            if info.st_uid not in (0, os.geteuid()) or (
                mode & 0o022 and not (info.st_uid == 0 and mode & stat.S_ISVTX)
            ):
                raise MacRuntimeError("runtime_unavailable")
            next_fd = os.open(part, flags, dir_fd=fd)
            previous, fd = fd, next_fd
            _close_all([previous])
        info = os.fstat(fd)
        if not (
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700
        ):
            raise MacRuntimeError("runtime_unavailable")
        result, fd = fd, None
        return result
    finally:
        _close_all([fd])


def _check_file(directory, name, fd, expected=None):
    info = os.fstat(fd)
    entry = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if not (
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and info.st_size == 0
        and _identity(info) == _identity(entry)
        and (expected is None or _identity(info) == expected)
    ):
        raise MacRuntimeError("runtime_unavailable")
    return _identity(info)


def _lock_file(directory, name, expected=None):
    import fcntl

    fd = None
    try:
        # O_NONBLOCK also prevents a malicious pre-existing FIFO from blocking open.
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            0o600,
            dir_fd=directory,
        )
        _check_file(directory, name, fd, expected)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise MacRuntimeError("runtime_busy") from None
            raise
        identity = _check_file(directory, name, fd, expected)
        result, fd = fd, None
        return result, identity
    finally:
        _close_all([fd])


class SlotLease(LocalResource):
    __slots__ = ("_owner", "_fd", "_identity")

    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("slots are issued by a runtime owner")
        return super().__new__(cls)

    def __init__(self, key, owner, fd, identity):
        if key is not _ISSUE or self in _SLOTS:
            raise TypeError("slots are issued once")
        self._owner, self._fd, self._identity = owner, fd, identity
        _SLOTS.add(self)

    def fileno(self):
        owner = getattr(self, "_owner", None)
        if type(self) is not SlotLease or self not in _SLOTS or type(owner) is not RuntimeOwner:
            raise MacRuntimeError("invalid_handle")
        owner._check_origin()
        with owner._mutex:
            owner._check_slot(self)
            return self._fd


class RuntimeOwner(LocalResource):
    __slots__ = ("_root", "_directory", "_fd", "_identity", "_pid", "_slot", "_mutex")

    def __new__(cls, key=None, *args):
        if key is not _ISSUE:
            raise TypeError("owners are issued by acquire_owner")
        return super().__new__(cls)

    def __init__(self, key, root, directory, fd, identity):
        if key is not _ISSUE or self in _OWNERS:
            raise TypeError("owners are issued once")
        self._root, self._directory, self._fd = root, directory, fd
        self._identity, self._pid, self._slot = identity, os.getpid(), None
        self._mutex = threading.Lock()
        _OWNERS.add(self)

    def _check_origin(self):
        if type(self) is not RuntimeOwner or self not in _OWNERS or self._pid != os.getpid():
            raise MacRuntimeError("invalid_handle")

    def _check_live(self):
        if self._fd is None:
            raise MacRuntimeError("invalid_handle")

    def _check_path(self):
        self._check_live()
        probe = _directory(self._root)
        try:
            if _identity(os.fstat(probe)) != _identity(os.fstat(self._directory)):
                raise MacRuntimeError("runtime_unavailable")
            _check_file(self._directory, "runtime.owner", self._fd, self._identity)
        finally:
            _close_all([probe])

    def _check_slot(self, slot):
        self._check_live()
        if (
            type(slot) is not SlotLease
            or slot not in _SLOTS
            or slot is not self._slot
            or slot._fd is None
        ):
            raise MacRuntimeError("invalid_handle")

    def reserve_slot(self):
        self._check_origin()
        with self._mutex:
            self._check_live()
            if self._slot is not None:
                raise MacRuntimeError("runtime_busy")
            try:
                self._check_path()
                fd, identity = _lock_file(self._directory, "analysis.slot")
                slot = SlotLease(_ISSUE, self, fd, identity)
                self._slot = slot
                return slot
            except MacRuntimeError:
                raise
            except Exception:
                raise MacRuntimeError("runtime_unavailable") from None

    def release_slot(self, slot):
        self._check_origin()
        with self._mutex:
            self._check_slot(slot)
            try:
                self._check_path()
                _check_file(self._directory, "analysis.slot", slot._fd, slot._identity)
                fd, slot._fd = slot._fd, None
                self._slot = None
                _close_all([fd])
                try:
                    probe, _ = _lock_file(self._directory, "analysis.slot", slot._identity)
                except MacRuntimeError as error:
                    if error.code == "runtime_busy":
                        return False
                    raise
                _close_all([probe])
                return True
            except MacRuntimeError:
                raise
            except Exception:
                raise MacRuntimeError("runtime_unavailable") from None

    def close(self):
        self._check_origin()
        with self._mutex:
            if self._slot is not None:
                raise MacRuntimeError("runtime_busy")
            self._close_references()

    def abandon(self):
        self._check_origin()
        with self._mutex:
            self._close_references()

    def _close_references(self):
        fds = []
        if self._slot is not None:
            fds.append(self._slot._fd)
            self._slot._fd = None
            self._slot = None
        fds.extend((self._fd, self._directory))
        self._fd, self._directory = None, None
        _close_all(fds)


def acquire_owner(root):
    if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
        raise MacRuntimeError("validation_error")
    if sys.platform != "darwin":
        raise MacRuntimeError("platform_unavailable")
    directory = fd = None
    try:
        directory = _directory(root)
        fd, identity = _lock_file(directory, "runtime.owner")
        owner = RuntimeOwner(_ISSUE, root, directory, fd, identity)
        directory = fd = None
        return owner
    except MacRuntimeError:
        raise
    except Exception:
        raise MacRuntimeError("runtime_unavailable") from None
    finally:
        _close_all([fd, directory])
