"""Explicit local NTFS validation; never discover or repair application directories."""

import ctypes as c
import re
from dataclasses import dataclass

from ._abi import DWORD, HANDLE, Native
from ._errors import WindowsRuntimeError
from ._handles import OwnedHandle, close_all
from ._security import descriptor, read_security, require_private, sid_at


@dataclass(frozen=True, slots=True)
class FileInfo:
    identity: tuple
    attributes: int
    size: int
    links: int
    delete_pending: bool
    final_path: str
    security: object


def root_parts(root):
    if type(root) is not str:
        raise WindowsRuntimeError("validation_error")
    try:
        units = len(root.encode("utf-16-le")) // 2
    except UnicodeError:
        raise WindowsRuntimeError("validation_error") from None
    if not 4 <= units <= 4095 or not re.match(r"^[A-Za-z]:\\", root):
        raise WindowsRuntimeError("validation_error")
    parts = root[3:].split("\\")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"}
    reserved |= {p + n for p in ("COM", "LPT") for n in "123456789¹²³"}
    if len(parts) > 64 or any(
        not p
        or p in (".", "..")
        or p[-1] in ". "
        or p.split(".")[0].rstrip(" .").upper() in reserved
        or any(ord(ch) < 32 or ch in '/:<>"|?*' for ch in p)
        for p in parts
    ):
        raise WindowsRuntimeError("validation_error")
    paths = [root[:3]]
    for part in parts:
        paths.append(paths[-1].rstrip("\\") + "\\" + part)
    return paths


class NativeFilesystem:
    def __init__(self):
        self.native = Native()

    def user(self):
        n = self.native
        token = HANDLE()
        if n.security.OpenThreadToken(n.kernel.GetCurrentThread(), 8, True, c.byref(token)):
            n.close(token.value)
            raise WindowsRuntimeError("runtime_unavailable")
        if c.get_last_error() != 1008:
            raise WindowsRuntimeError("runtime_unavailable")
        if not n.security.OpenProcessToken(n.kernel.GetCurrentProcess(), 8, c.byref(token)):
            raise WindowsRuntimeError("runtime_unavailable")
        owned = OwnedHandle(n, token.value)
        try:
            length = DWORD()
            result = n.security.GetTokenInformation(token, 1, None, 0, c.byref(length))
            error = c.get_last_error()
            if result or error != 122 or not 16 <= length.value <= 65536:
                raise WindowsRuntimeError("runtime_unavailable")
            buffer = c.create_string_buffer(length.value)
            if not n.security.GetTokenInformation(token, 1, buffer, len(buffer), c.byref(length)):
                raise WindowsRuntimeError("runtime_unavailable")
            pointer = c.cast(buffer, c.POINTER(HANDLE)).contents.value
            if pointer is None:
                raise WindowsRuntimeError("runtime_unavailable")
            return sid_at(buffer.raw, pointer - c.addressof(buffer))
        finally:
            owned.close()

    def directory(self, path, private=False):
        value = self.native.kernel.CreateFileW(
            path, 0x20080, 1 if private else 3, None, 3, 0x2200000, None
        )
        return self._opened(value)

    def _opened(self, value):
        if value in (None, 0, 2**64 - 1):
            error = c.get_last_error()
            raise WindowsRuntimeError("runtime_busy" if error == 32 else "runtime_unavailable")
        return OwnedHandle(self.native, value)

    def file(self, path, create, sid):
        handle = None
        try:
            with descriptor(self.native, sid) as sa:
                value = self.native.kernel.CreateFileW(
                    path, 0xC0020000, 0, c.byref(sa), 4 if create else 3, 0x200000, None
                )
                handle = self._opened(value)
            return handle
        except Exception:
            close_all([handle])
            raise

    def local_ntfs(self, handle, drive):
        name = c.create_unicode_buffer(64)
        if self.native.kernel.GetDriveTypeW(drive) != 3:
            raise WindowsRuntimeError("runtime_unavailable")
        if (
            not self.native.kernel.GetVolumeInformationByHandleW(
                handle.value, None, 0, None, None, None, name, len(name)
            )
            or name.value != "NTFS"
        ):
            raise WindowsRuntimeError("runtime_unavailable")

    def same_name(self, left, right):
        result = self.native.kernel.CompareStringOrdinal(left, -1, right, -1, True)
        if result not in (1, 2, 3):
            raise WindowsRuntimeError("runtime_unavailable")
        return result == 2

    def final_path(self, value):
        size = 512
        for _ in range(2):
            buffer = c.create_unicode_buffer(size)
            result = self.native.kernel.GetFinalPathNameByHandleW(value, buffer, size, 0)
            if not result or result >= 32768:
                raise WindowsRuntimeError("runtime_unavailable")
            if result < size:
                text = buffer.value
                if not re.match(r"^\\\\\?\\[A-Za-z]:\\", text):
                    raise WindowsRuntimeError("runtime_unavailable")
                return text[4:]
            size = result + 1
        raise WindowsRuntimeError("runtime_unavailable")

    def inspect(self, handle):
        from ._abi import FILE_ATTRIBUTE_TAG_INFO, FILE_ID_INFO, FILE_STANDARD_INFO

        n, value = self.native, handle.value
        flags = DWORD()
        if (
            n.kernel.GetFileType(value) != 1
            or not n.kernel.GetHandleInformation(value, c.byref(flags))
            or flags.value
        ):
            raise WindowsRuntimeError("runtime_unavailable")
        identity = n.info(value, 18, FILE_ID_INFO)
        standard = n.info(value, 1, FILE_STANDARD_INFO)
        attributes = n.info(value, 9, FILE_ATTRIBUTE_TAG_INFO)
        if (
            bool(attributes.FileAttributes & 16) != bool(standard.Directory)
            or attributes.ReparseTag
        ):
            raise WindowsRuntimeError("runtime_unavailable")
        return FileInfo(
            (identity.VolumeSerialNumber, bytes(identity.FileId)),
            attributes.FileAttributes,
            standard.EndOfFile,
            standard.NumberOfLinks,
            bool(standard.DeletePending),
            self.final_path(value),
            read_security(n, value),
        )


def _load_filesystem():
    return NativeFilesystem()


def check_info(fs, handle, path, *, directory, sid=None, volume=None, identity=None):
    info = fs.inspect(handle)
    forbidden = 0x400 | 0x1000 | 0x40000 | 0x400000
    if not directory:
        forbidden |= 0x4000 | 0x800 | 0x200 | 4 | 1
    if (
        type(info) is not FileInfo
        or bool(info.attributes & 16) != directory
        or info.attributes & forbidden
        or info.delete_pending
        or not fs.same_name(info.final_path, path)
        or (volume is not None and info.identity[0] != volume)
        or (identity is not None and info.identity != identity)
        or (not directory and (info.size != 0 or info.links != 1))
    ):
        raise WindowsRuntimeError("runtime_unavailable")
    if sid is not None:
        require_private(info.security, sid, directory)
    return info.identity


def pin_root(fs, paths, sid):
    pins, volume = [], None
    try:
        for pos, path in enumerate(paths):
            final = pos == len(paths) - 1
            handle = fs.directory(path, private=final)
            pins.append((path, handle, None))
            identity = check_info(
                fs, handle, path, directory=True, sid=sid if final else None, volume=volume
            )
            volume = identity[0]
            pins[-1] = (path, handle, identity)
        fs.local_ntfs(pins[-1][1], paths[0])
        return pins
    except Exception:
        close_all([item[1] for item in pins])
        raise


def recheck_root(fs, pins, sid):
    for pos, (path, handle, identity) in enumerate(pins):
        check_info(
            fs,
            handle,
            path,
            directory=True,
            sid=sid if pos == len(pins) - 1 else None,
            identity=identity,
        )
    probe = fs.directory(pins[-1][0], private=True)
    try:
        check_info(fs, probe, pins[-1][0], directory=True, sid=sid, identity=pins[-1][2])
        fs.local_ntfs(probe, pins[0][0])
    finally:
        probe.close()
