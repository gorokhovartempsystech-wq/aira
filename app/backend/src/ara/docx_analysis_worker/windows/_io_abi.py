"""Explicit Windows overlapped pipe/event binding. No DLL loads during import."""

import ctypes as c

from ._abi import BOOL, DWORD, HANDLE, Native, _bind
from ._errors import WindowsRuntimeError
from ._handles import OwnedHandle, close_all
from ._paths import NativeFilesystem
from ._security import descriptor


class OVERLAPPED(c.Structure):
    _fields_ = [
        ("Internal", c.c_size_t),
        ("InternalHigh", c.c_size_t),
        ("Offset", DWORD),
        ("OffsetHigh", DWORD),
        ("hEvent", HANDLE),
    ]


class IO:
    def __init__(self):
        self.base = Native()
        self.kernel = self.base.kernel
        k = self.kernel
        for name, args, result in [
            ("CreateEventW", [c.c_void_p, BOOL, BOOL, c.c_wchar_p], HANDLE),
            ("SetEvent", [HANDLE], BOOL),
            ("WaitForSingleObject", [HANDLE, DWORD], DWORD),
            (
                "CreateNamedPipeW",
                [c.c_wchar_p, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, c.c_void_p],
                HANDLE,
            ),
            ("ConnectNamedPipe", [HANDLE, c.POINTER(OVERLAPPED)], BOOL),
            ("ReadFile", [HANDLE, c.c_void_p, DWORD, c.c_void_p, c.POINTER(OVERLAPPED)], BOOL),
            ("WriteFile", [HANDLE, c.c_void_p, DWORD, c.c_void_p, c.POINTER(OVERLAPPED)], BOOL),
            ("GetOverlappedResult", [HANDLE, c.POINTER(OVERLAPPED), c.POINTER(DWORD), BOOL], BOOL),
            ("CancelIoEx", [HANDLE, c.POINTER(OVERLAPPED)], BOOL),
            ("GetNamedPipeClientProcessId", [HANDLE, c.POINTER(DWORD)], BOOL),
            ("GetNamedPipeServerProcessId", [HANDLE, c.POINTER(DWORD)], BOOL),
            ("GetCurrentProcessId", [], DWORD),
        ]:
            _bind(k, name, args, result)

    def _owned(self, value):
        return OwnedHandle(self, value)

    def close(self, value):
        self.base.close(value)

    def duplicate(self, value, inheritable):
        return self.base.duplicate(value, inheritable)

    def event(self):
        return self._owned(self.kernel.CreateEventW(None, True, False, None))

    def set_event(self, value):
        if not self.kernel.SetEvent(value):
            raise WindowsRuntimeError("runtime_unavailable")

    def wait_event(self, value, timeout):
        result = self.kernel.WaitForSingleObject(value, timeout)
        if result not in (0, 258):
            raise WindowsRuntimeError("runtime_unavailable")
        return result == 0

    def user(self):
        fs = object.__new__(NativeFilesystem)
        fs.native = self.base
        return fs.user()

    def server(self, name, sid):
        handle = None
        try:
            with descriptor(self.base, sid) as sa:
                handle = self._owned(
                    self.kernel.CreateNamedPipeW(
                        name, 0x40080001, 8, 1, 65536, 65536, 0, c.byref(sa)
                    )
                )
            return handle
        except Exception:
            close_all([handle])
            raise

    def client(self, name, synchronous):
        return self._owned(
            self.kernel.CreateFileW(
                name, 0x40000080, 0, None, 3, 0 if synchronous else 0x40000000, None
            )
        )

    def pid(self):
        return self.kernel.GetCurrentProcessId()

    def peer_processes(self, server, client):
        reader, writer = DWORD(), DWORD()
        if not self.kernel.GetNamedPipeClientProcessId(
            server, c.byref(reader)
        ) or not self.kernel.GetNamedPipeServerProcessId(server, c.byref(writer)):
            raise WindowsRuntimeError("runtime_unavailable")
        if self.kernel.GetFileType(client) != 3:
            raise WindowsRuntimeError("runtime_unavailable")
        return reader.value, writer.value

    @staticmethod
    def _status(result):
        return 0 if result else (c.get_last_error() or -1)

    def connect(self, handle, overlapped):
        return self._status(self.kernel.ConnectNamedPipe(handle, c.byref(overlapped)))

    def read(self, handle, buffer, size, overlapped):
        return self._status(self.kernel.ReadFile(handle, buffer, size, None, c.byref(overlapped)))

    def write(self, handle, buffer, size, overlapped):
        return self._status(self.kernel.WriteFile(handle, buffer, size, None, c.byref(overlapped)))

    def result(self, handle, overlapped):
        count = DWORD()
        status = self._status(
            self.kernel.GetOverlappedResult(handle, c.byref(overlapped), c.byref(count), False)
        )
        return status, count.value

    def cancel(self, handle, overlapped):
        if not self.kernel.CancelIoEx(handle, c.byref(overlapped)) and c.get_last_error() != 1168:
            raise WindowsRuntimeError("runtime_unavailable")


def _load_io():
    return IO()
