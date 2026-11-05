"""Darwin private data directory and exclusive durable identity publication."""

import ctypes
import os
import stat
from contextlib import contextmanager

from ._models import ALLOWED, IDENTITY, OWNER, PENDING, HomeError, require

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _identity(info):
    return info.st_dev, info.st_ino


def _stamp(info):
    return (
        *_identity(info),
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _parent(info):
    require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.geteuid()), "home_unavailable")
    mode = stat.S_IMODE(info.st_mode)
    require(not mode & 0o022 or (info.st_uid == 0 and mode & stat.S_ISVTX), "home_unavailable")


def _directory(info):
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "home_unavailable",
    )


def _file(info):
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and 0 <= info.st_size <= 1024
    )


class Filesystem:
    def __init__(self, root):
        self.root = root
        self.parent = self.directory = None
        self.key = None
        self.uncertain = False

    def close_fd(self, fd):
        if fd is not None:
            try:
                os.close(fd)
            except BaseException:
                self.uncertain = True
                raise HomeError() from None

    def open(self):
        self.parent = os.open("/", FLAGS)
        for part in self.root.parts[1:-1]:
            _parent(os.fstat(self.parent))
            current = os.open(part, FLAGS, dir_fd=self.parent)
            previous, self.parent = self.parent, current
            self.close_fd(previous)
        _parent(os.fstat(self.parent))
        try:
            os.mkdir(self.root.name, 0o700, dir_fd=self.parent)
        except FileExistsError:
            pass
        else:
            os.fsync(self.parent)
        self.directory = os.open(self.root.name, FLAGS, dir_fd=self.parent)
        info = os.fstat(self.directory)
        _directory(info)
        self.key = _identity(info)
        self.recheck()
        self.entries()
        self.inspect_owner()
        return self.key

    def recheck(self):
        info = os.fstat(self.directory)
        named = os.stat(self.root, follow_symlinks=False)
        _directory(info)
        _directory(named)
        require(_identity(info) == _identity(named) == self.key, "home_unavailable")

    def entries(self):
        self.recheck()
        names = set()
        with os.scandir(self.directory) as entries:
            for entry in entries:
                require(entry.name in ALLOWED)
                names.add(entry.name)
        return names

    def inspect_owner(self):
        try:
            info = os.stat(OWNER, dir_fd=self.directory, follow_symlinks=False)
        except FileNotFoundError:
            return
        _file(info)
        require(info.st_size == 0)

    def acquire_owner(self):
        from ara.docx_analysis_worker.macos import acquire_owner

        return acquire_owner(self.root)

    @contextmanager
    def file(self, name, *, writable=False, publishing=False):
        self.recheck()
        info = os.stat(name, dir_fd=self.directory, follow_symlinks=False)
        _file(info)
        fd = os.open(
            name,
            (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=self.directory,
        )
        try:
            opened = os.fstat(fd)
            _file(opened)
            require(_stamp(info) == _stamp(opened))
            yield fd, info
            before, after = _stamp(info), _stamp(os.fstat(fd))
            # Our own rename may change ctime; it must not change bytes or identity.
            require(before[:-1] == after[:-1] if publishing else before == after)
            self.recheck()
        finally:
            self.close_fd(fd)

    def read(self, name):
        try:
            # Distinguish absent state from a failed open after a successful observation.
            os.stat(name, dir_fd=self.directory, follow_symlinks=False)
        except FileNotFoundError:
            return None
        with self.file(name) as (fd, _):
            data = bytearray()
            while len(data) <= 1024:
                chunk = os.read(fd, 1025 - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            require(len(data) <= 1024)
            return bytes(data)

    def remove_pending(self, expected):
        require(self.entries() <= {OWNER, PENDING})
        require(self.read(PENDING) == expected)
        os.unlink(PENDING, dir_fd=self.directory)
        os.fsync(self.directory)

    def write_pending(self, raw):
        self.recheck()
        fd = os.open(
            PENDING,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=self.directory,
        )
        try:
            _file(os.fstat(fd))
            offset = 0
            while offset < len(raw):
                count = os.write(fd, raw[offset:])
                require(type(count) is int and 0 < count <= len(raw) - offset, "home_unavailable")
                offset += count
            os.fsync(fd)
            self.full_sync(fd)
        finally:
            self.close_fd(fd)

    @staticmethod
    def full_sync(fd):
        import fcntl

        require(fcntl.fcntl(fd, 51) == 0, "home_unavailable")

    def publish_pending(self, raw):
        require(self.read(PENDING) == raw)
        # Keep the source FD through rename and the final storage barrier.
        with self.file(PENDING, writable=True, publishing=True) as (fd, _):
            os.fsync(fd)
            self.full_sync(fd)
            native = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
            rename = native.renameatx_np
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            rename.restype = ctypes.c_int
            require(
                rename(self.directory, PENDING.encode(), self.directory, IDENTITY.encode(), 4) == 0,
                "home_unavailable",
            )
            require(
                _identity(os.stat(IDENTITY, dir_fd=self.directory, follow_symlinks=False))
                == _identity(os.fstat(fd))
            )
            os.fsync(self.directory)
            self.full_sync(fd)

    def ensure_child(self, name):
        self.recheck()
        try:
            os.mkdir(name, 0o700, dir_fd=self.directory)
        except FileExistsError:
            pass
        fd = os.open(name, FLAGS, dir_fd=self.directory)
        try:
            info = os.fstat(fd)
            named = os.stat(name, dir_fd=self.directory, follow_symlinks=False)
            _directory(info)
            require(_identity(info) == _identity(named), "home_unavailable")
            os.fsync(fd)
        finally:
            self.close_fd(fd)
        os.fsync(self.directory)

    def sync_existing(self):
        with self.file(IDENTITY, writable=True) as (fd, _):
            os.fsync(fd)
            os.fsync(self.directory)
            os.fsync(self.parent)
            self.full_sync(fd)

    def close(self):
        failed = self.uncertain
        for name in ("directory", "parent"):
            fd = getattr(self, name)
            setattr(self, name, None)
            try:
                self.close_fd(fd)
            except HomeError:
                failed = True
        require(not failed, "home_unavailable")
