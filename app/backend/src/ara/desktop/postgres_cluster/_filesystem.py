"""Pinned private layout and no-replace journal publication on Darwin."""

import ctypes
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from ._models import ClusterError, require

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
RECORDS = {"initialization.json", "prepared.json", "cluster.json"}
CONFIGS = {"server.conf", "pg_hba.conf", "pg_ident.conf"}
LOCKS = {"runtime.owner", "analysis.slot"}
STAGE = ".data18.pending"
DATA = "data18"
TEMPS = {"." + name + ".pending" for name in RECORDS | CONFIGS}


def identity(info):
    return info.st_dev, info.st_ino


def stamp(info):
    return (
        *identity(info),
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def directory(info):
    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def private_file(info, limit=4096):
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and 0 <= info.st_size <= limit
    )


def retained(name):
    if not name.startswith("failed-init-"):
        return False
    try:
        value = UUID(name[12:])
    except ValueError:
        return False
    return value.version == 4 and str(value) == name[12:]


class Filesystem:
    def __init__(self, root):
        self.root = root
        self.fd = self.key = None
        self.socket_parent = self.socket_fd = self.socket_name = self.socket_key = None
        self.uncertain = False

    def close_fd(self, fd):
        if fd is not None:
            try:
                os.close(fd)
            except BaseException:
                self.uncertain = True
                raise ClusterError("cleanup_unknown") from None

    def walk(self, path):
        fd = os.open("/", FLAGS)
        try:
            for part in path.parts[1:]:
                info = os.fstat(fd)
                mode = stat.S_IMODE(info.st_mode)
                require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.geteuid()))
                require(not mode & 0o022 or (info.st_uid == 0 and mode & stat.S_ISVTX))
                next_fd = os.open(part, FLAGS, dir_fd=fd)
                previous, fd = fd, next_fd
                self.close_fd(previous)
            result, fd = fd, None
            return result
        finally:
            self.close_fd(fd)

    def open(self):
        self.fd = self.walk(self.root)
        directory(os.fstat(self.fd))
        self.key = identity(os.fstat(self.fd))
        self.entries()

    def recheck(self):
        probe = self.walk(self.root)
        try:
            directory(os.fstat(probe))
            directory(os.fstat(self.fd))
            require(identity(os.fstat(probe)) == identity(os.fstat(self.fd)) == self.key)
        finally:
            self.close_fd(probe)

    def entries(self):
        self.recheck()
        names = set()
        with os.scandir(self.fd) as entries:
            for entry in entries:
                name = entry.name
                require(name in RECORDS | CONFIGS | LOCKS | TEMPS | {DATA, STAGE} or retained(name))
                require(len(names) < 20)
                info = entry.stat(follow_symlinks=False)
                if name in (DATA, STAGE) or retained(name):
                    directory(info)
                else:
                    private_file(info, 0 if name in LOCKS else 4096)
                names.add(name)
        require(sum(retained(name) for name in names) <= 3)
        return names

    def bind(self, slot):
        self.recheck()
        info = os.stat("analysis.slot", dir_fd=self.fd, follow_symlinks=False)
        private_file(info, 0)
        require(identity(info) == identity(os.fstat(slot.fileno())))

    @contextmanager
    def file(self, name, *, parent=None, writable=False, publishing=False, removing=False):
        self.recheck()
        parent = self.fd if parent is None else parent
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        private_file(info)
        fd = os.open(
            name,
            (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent,
        )
        try:
            opened = os.fstat(fd)
            private_file(opened)
            require(stamp(info) == stamp(opened))
            yield fd
            after = os.fstat(fd)
            if removing:
                require(
                    identity(info) == identity(after)
                    and after.st_nlink == 0
                    and info.st_size == after.st_size
                    and info.st_mtime_ns == after.st_mtime_ns
                )
            else:
                require(
                    stamp(info)[:-1] == stamp(after)[:-1]
                    if publishing
                    else stamp(info) == stamp(after)
                )
                if not publishing:
                    require(
                        stamp(after) == stamp(os.stat(name, dir_fd=parent, follow_symlinks=False))
                    )
            self.recheck()
        finally:
            self.close_fd(fd)

    def read(self, name):
        self.recheck()
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        with self.file(name) as fd:
            raw = bytearray()
            while len(raw) <= 4096:
                chunk = os.read(fd, 4097 - len(raw))
                if not chunk:
                    break
                raw.extend(chunk)
            require(len(raw) <= 4096)
            return bytes(raw)

    @staticmethod
    def full_sync(fd):
        import fcntl

        require(fcntl.fcntl(fd, 51) == 0, "cluster_unavailable")

    def sync(self, fd):
        os.fsync(fd)
        os.fsync(self.fd)
        self.full_sync(fd)

    def rename(self, source, target):
        self.recheck()
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
            rename(self.fd, source.encode(), self.fd, target.encode(), 4) == 0,
            "cluster_unavailable",
        )

    def publish(self, name, raw):
        require(name in RECORDS | CONFIGS and type(raw) is bytes and 0 < len(raw) <= 4096)
        pending = "." + name + ".pending"
        existing = self.read(name)
        if existing is not None:
            require(existing == raw and self.read(pending) is None)
            with self.file(name, writable=True) as fd:
                self.sync(fd)
            return
        partial = self.read(pending)
        if partial is None:
            self.recheck()
            fd = os.open(
                pending,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=self.fd,
            )
            try:
                private_file(os.fstat(fd))
                offset = 0
                while offset < len(raw):
                    count = os.write(fd, raw[offset:])
                    require(
                        type(count) is int and 0 < count <= len(raw) - offset, "cluster_unavailable"
                    )
                    offset += count
                os.fsync(fd)
                self.full_sync(fd)
            finally:
                self.close_fd(fd)
        else:
            require(partial == raw)
        with self.file(pending, writable=True, publishing=True) as fd:
            os.fsync(fd)
            self.full_sync(fd)
            self.rename(pending, name)
            require(
                identity(os.fstat(fd))
                == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False))
            )
            self.sync(fd)
            require(
                identity(os.fstat(fd))
                == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False))
            )

    def remove(self, name, expected):
        require(name in RECORDS | TEMPS)
        require(self.read(name) == expected)
        with self.file(name, writable=True, removing=True) as fd:
            os.unlink(name, dir_fd=self.fd)
            os.fsync(self.fd)
            self.full_sync(fd)

    def move_directory(self, source, target):
        self.recheck()
        fd = os.open(source, FLAGS, dir_fd=self.fd)
        try:
            directory(os.fstat(fd))
            require(
                identity(os.fstat(fd))
                == identity(os.stat(source, dir_fd=self.fd, follow_symlinks=False))
            )
            self.rename(source, target)
            require(
                identity(os.fstat(fd))
                == identity(os.stat(target, dir_fd=self.fd, follow_symlinks=False))
            )
            self.sync(fd)
        finally:
            self.close_fd(fd)

    def check_version(self, name):
        self.recheck()
        fd = os.open(name, FLAGS, dir_fd=self.fd)
        try:
            directory(os.fstat(fd))
            with self.file("PG_VERSION", parent=fd) as version:
                require(os.read(version, 16) == b"18\n")
            require(
                identity(os.fstat(fd))
                == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False))
            )
        finally:
            self.close_fd(fd)

    def make_socket(self, path):
        path = Path(path)
        self.socket_parent = self.walk(path.parent)
        # The name is fresh; never adopt a preexisting endpoint.
        os.mkdir(path.name, 0o700, dir_fd=self.socket_parent)
        self.socket_name = path.name
        self.socket_fd = os.open(path.name, FLAGS, dir_fd=self.socket_parent)
        directory(os.fstat(self.socket_fd))
        self.socket_key = identity(os.fstat(self.socket_fd))
        require(
            self.socket_key
            == identity(os.stat(path.name, dir_fd=self.socket_parent, follow_symlinks=False))
        )

    def close(self):
        # This is called only after the owned command has confirmed completion.
        if self.socket_name is not None:
            require(self.socket_fd is not None and self.socket_key is not None, "cleanup_unknown")
            directory(os.fstat(self.socket_fd))
            info = os.stat(self.socket_name, dir_fd=self.socket_parent, follow_symlinks=False)
            directory(info)
            require(identity(info) == self.socket_key, "cleanup_unknown")
            require(not os.listdir(self.socket_fd), "cleanup_unknown")
            os.rmdir(self.socket_name, dir_fd=self.socket_parent)
            self.socket_name = None
        for attr in ("socket_fd", "socket_parent", "fd"):
            fd = getattr(self, attr)
            setattr(self, attr, None)
            self.close_fd(fd)
        require(not self.uncertain, "cleanup_unknown")
