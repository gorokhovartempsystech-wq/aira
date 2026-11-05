"""Atomic public activation identity, never an offline authorization or secret file."""

import ctypes
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from ._models import ActivationIdentity, checked_identity, require, safe

_NAME = "license-activation.json"
_SCHEMA = "aira-license-activation/1"
_ERROR = "activation_store_error"


def _valid_file(info):
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, _ERROR)
    require(not getattr(info, "st_file_attributes", 0) & 0x400, _ERROR)
    if os.name == "posix":
        require(info.st_uid == os.getuid(), _ERROR)


def _valid_root(info):
    require(stat.S_ISDIR(info.st_mode), _ERROR)
    require(not getattr(info, "st_file_attributes", 0) & 0x400, _ERROR)
    if os.name == "posix":
        require(info.st_uid == os.getuid() and info.st_mode & 0o022 == 0, _ERROR)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, _ERROR)
        result[key] = value
    return result


def _decode(data):
    require(len(data) <= 1024, _ERROR)
    parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    require(
        type(parsed) is dict and set(parsed) == {"schema_version", "license_id", "device_id"},
        _ERROR,
    )
    require(parsed["schema_version"] == _SCHEMA and type(parsed["license_id"]) is str, _ERROR)
    value = UUID(parsed["license_id"])
    require(str(value) == parsed["license_id"], _ERROR)
    return checked_identity(ActivationIdentity(value, parsed["device_id"]), _ERROR)


def _windows_replace(source, target):
    move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    move.restype = ctypes.c_int32
    require(move(str(source), str(target), 0x1 | 0x8), _ERROR)


class ActivationStore:
    def __init__(self, root):
        require(
            isinstance(root, Path) and root.is_absolute() and ".." not in root.parts,
            "validation_error",
        )
        self._root = root

    @contextmanager
    def _directory(self, create=False):
        if create:
            try:
                self._root.mkdir(mode=0o700)
            except FileExistsError:
                pass
        info = self._root.lstat()
        _valid_root(info)
        if os.name != "posix":
            yield None
            return
        fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(fd)
            _valid_root(opened)
            require((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino), _ERROR)
            yield fd
        finally:
            os.close(fd)

    def _path(self, name, directory):
        return name if directory is not None else self._root / name

    def _stat(self, name, directory):
        return os.stat(self._path(name, directory), dir_fd=directory, follow_symlinks=False)

    @safe(_ERROR)
    def load(self):
        try:
            with self._directory() as directory:
                info = self._stat(_NAME, directory)
                _valid_file(info)
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0)
                )
                fd = os.open(self._path(_NAME, directory), flags, dir_fd=directory)
                try:
                    opened = os.fstat(fd)
                    _valid_file(opened)
                    require((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino), _ERROR)
                    data = bytearray()
                    while len(data) <= 1024:
                        chunk = os.read(fd, 1025 - len(data))
                        if not chunk:
                            break
                        data.extend(chunk)
                    return _decode(bytes(data))
                finally:
                    os.close(fd)
        except FileNotFoundError:
            return None

    @safe(_ERROR)
    def save(self, identity):
        identity = checked_identity(identity)
        data = json.dumps(
            {
                "schema_version": _SCHEMA,
                "license_id": str(identity.license_id),
                "device_id": identity.device_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        with self._directory(create=True) as directory:
            try:
                _valid_file(self._stat(_NAME, directory))
            except FileNotFoundError:
                pass
            name = ".license-activation." + uuid4().hex + ".tmp"
            fd = None
            own = None
            try:
                fd = os.open(
                    self._path(name, directory),
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory,
                )
                own = os.fstat(fd)
                _valid_file(own)
                offset = 0
                while offset < len(data):
                    count = os.write(fd, data[offset:])
                    require(type(count) is int and 0 < count <= len(data) - offset, _ERROR)
                    offset += count
                os.fsync(fd)
                closing, fd = fd, None
                os.close(closing)
                if directory is not None:
                    os.replace(name, _NAME, src_dir_fd=directory, dst_dir_fd=directory)
                    os.fsync(directory)
                else:
                    _windows_replace(self._root / name, self._root / _NAME)
            finally:
                try:
                    if fd is not None:
                        os.close(fd)
                finally:
                    if own is not None:
                        try:
                            current = self._stat(name, directory)
                            if (current.st_dev, current.st_ino) == (own.st_dev, own.st_ino):
                                os.unlink(self._path(name, directory), dir_fd=directory)
                        except FileNotFoundError:
                            pass
