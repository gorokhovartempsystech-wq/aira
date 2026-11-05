"""Explicit Windows known-folder, private NTFS identity and native publication."""

import ctypes as c
from contextlib import contextmanager
from uuid import UUID

from ara.docx_analysis_worker.windows import _paths
from ara.docx_analysis_worker.windows._abi import BOOL, DWORD, HANDLE, SECURITY_ATTRIBUTES, library
from ara.docx_analysis_worker.windows._handles import OwnedHandle, valid_handle
from ara.docx_analysis_worker.windows._security import descriptor, require_private

from ._models import ALLOWED, IDENTITY, OWNER, PENDING, HomeError, require


class GUID(c.Structure):
    _fields_ = [
        ("Data1", c.c_uint32),
        ("Data2", c.c_uint16),
        ("Data3", c.c_uint16),
        ("Data4", c.c_uint8 * 8),
    ]


def known_folder():
    shell, ole = library("shell32.dll"), library("ole32.dll")
    get = shell.SHGetKnownFolderPath
    get.argtypes = [c.POINTER(GUID), DWORD, HANDLE, c.POINTER(c.c_void_p)]
    get.restype = c.c_int32
    free = ole.CoTaskMemFree
    free.argtypes, free.restype = [c.c_void_p], None
    identifier = GUID.from_buffer_copy(UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
    result = c.c_void_p()
    try:
        require(
            get(c.byref(identifier), 0, None, c.byref(result)) == 0 and result.value,
            "home_unavailable",
        )
        # The OS returns a terminated path; retain no native allocation after this call.
        value = c.wstring_at(result.value)
        _paths.root_parts(value)
        return value
    finally:
        if result.value:
            free(result.value)


class Filesystem:
    def __init__(self, root):
        self.root = root
        self.fs = self.sid = self.key = None
        self.pins = []
        self.uncertain = False

    def bind(self):
        k = self.fs.native.kernel
        for name, args, result in (
            ("CreateDirectoryW", [c.c_wchar_p, c.POINTER(SECURITY_ATTRIBUTES)], BOOL),
            ("ReadFile", [HANDLE, c.c_void_p, DWORD, c.POINTER(DWORD), c.c_void_p], BOOL),
            ("WriteFile", [HANDLE, c.c_void_p, DWORD, c.POINTER(DWORD), c.c_void_p], BOOL),
            ("FlushFileBuffers", [HANDLE], BOOL),
            ("MoveFileExW", [c.c_wchar_p, c.c_wchar_p, DWORD], BOOL),
            ("DeleteFileW", [c.c_wchar_p], BOOL),
        ):
            function = getattr(k, name)
            function.argtypes, function.restype = args, result

    def close_handle(self, handle):
        if handle is not None:
            try:
                handle.close()
            except BaseException:
                self.uncertain = True
                raise HomeError() from None

    def _mkdir(self, path):
        with descriptor(self.fs.native, self.sid, directory=True) as sa:
            success = self.fs.native.kernel.CreateDirectoryW(path, c.byref(sa))
            error = c.get_last_error()
            require(success or error == 183, "home_unavailable")

    def open(self):
        paths = _paths.root_parts(str(self.root))
        self.fs = _paths.NativeFilesystem()
        self.sid = self.fs.user()
        self.bind()
        volume = None
        for path in paths[:-1]:
            handle = self.fs.directory(path)
            self.pins.append((path, handle, None))
            identity = _paths.check_info(self.fs, handle, path, directory=True, volume=volume)
            volume = identity[0]
            self.pins[-1] = (path, handle, identity)
        self.fs.local_ntfs(self.pins[-1][1], paths[0])
        self._mkdir(paths[-1])
        handle = self.fs.directory(paths[-1], private=True)
        self.pins.append((paths[-1], handle, None))
        identity = _paths.check_info(
            self.fs, handle, paths[-1], directory=True, volume=volume, sid=self.sid
        )
        self.pins[-1] = (paths[-1], handle, identity)
        self.key = identity
        self.recheck()
        self.entries()
        self.inspect_owner()
        return self.key

    def recheck(self):
        _paths.recheck_root(self.fs, self.pins, self.sid)

    def entries(self):
        import os

        self.recheck()
        names = set()
        with os.scandir(self.root) as entries:
            for entry in entries:
                require(entry.name in ALLOWED)
                names.add(entry.name)
        return names

    def _admit_file(self, handle, path):
        info = self.fs.inspect(handle)
        require(
            type(info) is _paths.FileInfo
            and not info.attributes
            & (0x10 | 0x400 | 0x1000 | 0x40000 | 0x400000 | 0x4000 | 0x800 | 0x200 | 4 | 1)
            and not info.delete_pending
            and info.links == 1
            and 0 <= info.size <= 1024
            and info.identity[0] == self.key[0]
            and self.fs.same_name(info.final_path, path)
        )
        require_private(info.security, self.sid, False)
        return info

    @contextmanager
    def file(self, name, *, create=False, writable=False, metadata=False):
        self.recheck()
        path = str(self.root / name)
        access = 0x20080 if metadata else (0xC0020080 if writable else 0x80020080)
        flags = 0x200000 | (0x80000000 if create else 0)
        k = self.fs.native.kernel
        if create:
            with descriptor(self.fs.native, self.sid) as sa:
                value = k.CreateFileW(path, access, 0, c.byref(sa), 1, flags, None)
                error = c.get_last_error()
        else:
            value = k.CreateFileW(path, access, 7 if metadata else 0, None, 3, flags, None)
            error = c.get_last_error()
        if not valid_handle(value):
            if not create and error == 2:
                yield None, None
                return
            raise HomeError("home_busy" if error == 32 else "home_unavailable")
        handle = OwnedHandle(self.fs.native, value)
        try:
            info = self._admit_file(handle, path)
            yield handle, info
            after = self._admit_file(handle, path)
            require(after.identity == info.identity and (writable or after.size == info.size))
            self.recheck()
        finally:
            self.close_handle(handle)

    def inspect_owner(self):
        with self.file(OWNER, metadata=True) as (handle, info):
            if handle is not None:
                require(info.size == 0)

    def acquire_owner(self):
        from ara.docx_analysis_worker.windows import acquire_owner

        return acquire_owner(str(self.root))

    def read(self, name):
        with self.file(name) as (handle, info):
            if handle is None:
                return None
            data = bytearray()
            while len(data) <= 1024:
                size = 1025 - len(data)
                buffer, count = c.create_string_buffer(size), DWORD()
                require(
                    self.fs.native.kernel.ReadFile(
                        handle.value, buffer, size, c.byref(count), None
                    ),
                    "home_unavailable",
                )
                require(count.value <= size, "home_unavailable")
                if not count.value:
                    break
                data.extend(buffer.raw[: count.value])
            require(len(data) == info.size and len(data) <= 1024)
            return bytes(data)

    def remove_pending(self, expected):
        require(self.entries() <= {OWNER, PENDING} and self.read(PENDING) == expected)
        require(self.fs.native.kernel.DeleteFileW(str(self.root / PENDING)), "home_unavailable")
        self.recheck()

    def write_pending(self, raw):
        with self.file(PENDING, create=True, writable=True) as (handle, _):
            offset = 0
            while offset < len(raw):
                data = c.create_string_buffer(raw[offset:])
                count = DWORD()
                require(
                    self.fs.native.kernel.WriteFile(
                        handle.value, data, len(raw) - offset, c.byref(count), None
                    ),
                    "home_unavailable",
                )
                require(0 < count.value <= len(raw) - offset, "home_unavailable")
                offset += count.value
            require(self.fs.native.kernel.FlushFileBuffers(handle.value), "home_unavailable")

    def _flush(self, name):
        with self.file(name, writable=True) as (handle, _):
            require(handle is not None, "home_recovery_required")
            require(self.fs.native.kernel.FlushFileBuffers(handle.value), "home_unavailable")

    def publish_pending(self, raw):
        require(self.read(PENDING) == raw)
        self._flush(PENDING)
        self.recheck()
        require(
            self.fs.native.kernel.MoveFileExW(
                str(self.root / PENDING), str(self.root / IDENTITY), 8
            ),
            "home_unavailable",
        )
        require(self.read(IDENTITY) == raw)
        self._flush(IDENTITY)

    def ensure_child(self, name):
        self.recheck()
        path = str(self.root / name)
        self._mkdir(path)
        handle = self.fs.directory(path, private=True)
        try:
            _paths.check_info(
                self.fs, handle, path, directory=True, sid=self.sid, volume=self.key[0]
            )
        finally:
            self.close_handle(handle)
        self.recheck()

    def sync_existing(self):
        self._flush(IDENTITY)

    def close(self):
        failed = self.uncertain
        while self.pins:
            _, handle, _ = self.pins.pop()
            try:
                self.close_handle(handle)
            except HomeError:
                failed = True
        require(not failed, "home_unavailable")
