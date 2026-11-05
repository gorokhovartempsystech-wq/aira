"""Pinned private directories and bounded durable records; never replace unknown files."""

import ctypes
import os
from uuid import UUID

from ara.desktop.postgres_cluster._filesystem import directory, identity, private_file
from ara.desktop.postgres_schema._journal import LOCKS, JournalFiles

from ._models import require


def canonical_id(name):
    try:
        value = UUID(name)
    except (ValueError, TypeError, AttributeError):
        return False
    return value.version == 4 and str(value) == name


class Files(JournalFiles):
    def __init__(self, root, records, *, backups=False, max_bytes=0):
        super().__init__(root)
        self.records = set(records)
        self.temps = {"." + name + ".pending" for name in records}
        self.backups = backups
        self.max_bytes = max_bytes

    def entries(self):
        self.recheck()
        names = set()
        with os.scandir(self.fd) as entries:
            for entry in entries:
                require(len(names) < 32)
                info = entry.stat(follow_symlinks=False)
                if self.backups and canonical_id(entry.name):
                    directory(info)
                elif self.max_bytes and entry.name in ("data.dump", "data.dump.pending"):
                    private_file(info, 8 * 1024**3)
                else:
                    require(entry.name in LOCKS | self.records | self.temps)
                    private_file(info, 0 if entry.name in LOCKS else 4096)
                names.add(entry.name)
        return names

    def stage(self, name, raw):
        require(type(raw) is bytes and 0 < len(raw) <= 4096)
        if self.read(name) is not None:
            require(self.read(name) == raw)
            return
        self.recheck()
        fd = os.open(
            name,
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
                    type(count) is int and 0 < count <= len(raw) - offset, "upgrade_unavailable"
                )
                offset += count
            os.fsync(fd)
            self.full_sync(fd)
        finally:
            self.close_fd(fd)
        require(self.read(name) == raw)

    def publish(self, name, raw):
        require(name in self.records)
        temp = "." + name + ".pending"
        if self.read(name) is not None:
            require(self.read(name) == raw and self.read(temp) is None)
            with self.file(name, writable=True) as fd:
                self.sync(fd)
            return
        self.stage(temp, raw)
        with self.file(temp, writable=True, publishing=True) as fd:
            self.rename(temp, name)
            require(
                identity(os.fstat(fd))
                == identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False))
            )
            self.sync(fd)

    def remove(self, name, expected):
        require(name in self.records | self.temps and self.read(name) == expected)
        with self.file(name, writable=True, removing=True) as fd:
            os.unlink(name, dir_fd=self.fd)
            os.fsync(self.fd)
            self.full_sync(fd)

    def exchange(self, old, new):
        temp = ".ready.json.pending"
        require(self.read("ready.json") == old and self.read(temp) == new)
        with self.file("ready.json", writable=True, publishing=True) as old_fd:
            with self.file(temp, writable=True, publishing=True) as new_fd:
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
                self.recheck()
                require(
                    rename(self.fd, b"ready.json", self.fd, temp.encode(), 2) == 0,
                    "upgrade_unavailable",
                )
                require(
                    identity(os.fstat(new_fd))
                    == identity(os.stat("ready.json", dir_fd=self.fd, follow_symlinks=False))
                )
                require(
                    identity(os.fstat(old_fd))
                    == identity(os.stat(temp, dir_fd=self.fd, follow_symlinks=False))
                )
                self.sync(new_fd)
                self.full_sync(old_fd)
        require(self.read("ready.json") == new and self.read(temp) == old)


class Ownership:
    def __init__(self, fs):
        self.fs = fs
        self.owner = None
        self.uncertain = False

    def open(self):
        from ara.docx_analysis_worker.macos import MacRuntimeError, acquire_owner

        self.fs.open()
        try:
            self.owner = acquire_owner(self.fs.root)
            slot = self.owner.reserve_slot()
        except MacRuntimeError as error:
            if error.code == "runtime_busy":
                require(False, "upgrade_busy")
            self.uncertain = True
            require(False, "cleanup_unknown")
        try:
            self.fs.bind(slot)
        finally:
            try:
                require(self.owner.release_slot(slot), "cleanup_unknown")
            except BaseException:
                self.uncertain = True
                raise

    def close(self):
        if self.uncertain:
            return False
        try:
            self.fs.close()
            if self.owner is not None:
                self.owner.close()
                self.owner = None
            return True
        except BaseException:
            self.uncertain = True
            return False
