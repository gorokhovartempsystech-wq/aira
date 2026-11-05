"""Windows x64 types and explicit system DLL bindings (also layout-testable on Mac)."""

import ctypes as c
import sys

from ._errors import WindowsRuntimeError

DWORD = c.c_uint32
BOOL = c.c_int32
WORD = WCHAR = c.c_uint16
DWORD64 = c.c_uint64
SIZE_T = c.c_size_t
HANDLE = c.c_void_p
PVOID = c.c_void_p
PDWORD = c.POINTER(DWORD)
PHANDLE = c.POINTER(HANDLE)


class SECURITY_ATTRIBUTES(c.Structure):
    _fields_ = [("nLength", DWORD), ("lpSecurityDescriptor", PVOID), ("bInheritHandle", BOOL)]


class FILE_ID_INFO(c.Structure):
    _fields_ = [("VolumeSerialNumber", DWORD64), ("FileId", c.c_ubyte * 16)]


class FILE_STANDARD_INFO(c.Structure):
    _fields_ = [
        ("AllocationSize", c.c_int64),
        ("EndOfFile", c.c_int64),
        ("NumberOfLinks", DWORD),
        ("DeletePending", c.c_ubyte),
        ("Directory", c.c_ubyte),
    ]


class FILE_ATTRIBUTE_TAG_INFO(c.Structure):
    _fields_ = [("FileAttributes", DWORD), ("ReparseTag", DWORD)]


def library(name):
    if sys.platform != "win32" or c.sizeof(HANDLE) != 8:
        raise WindowsRuntimeError("platform_unavailable")
    return c.WinDLL(name, use_last_error=True, winmode=0x800)


def _bind(dll, name, args, result):
    function = getattr(dll, name)
    function.argtypes, function.restype = args, result


class Native:
    def __init__(self):
        self.kernel, self.security = library("kernel32.dll"), library("advapi32.dll")
        k, a = self.kernel, self.security
        signatures = [
            (k, "CloseHandle", [HANDLE], BOOL),
            (k, "GetCurrentProcess", [], HANDLE),
            (k, "GetCurrentThread", [], HANDLE),
            (k, "DuplicateHandle", [HANDLE, HANDLE, HANDLE, PHANDLE, DWORD, BOOL, DWORD], BOOL),
            (k, "GetHandleInformation", [HANDLE, PDWORD], BOOL),
            (
                k,
                "CreateFileW",
                [c.c_wchar_p, DWORD, DWORD, c.POINTER(SECURITY_ATTRIBUTES), DWORD, DWORD, HANDLE],
                HANDLE,
            ),
            (k, "GetFileType", [HANDLE], DWORD),
            (k, "GetFileInformationByHandleEx", [HANDLE, c.c_int32, PVOID, DWORD], BOOL),
            (k, "GetFinalPathNameByHandleW", [HANDLE, c.c_wchar_p, DWORD, DWORD], DWORD),
            (k, "GetDriveTypeW", [c.c_wchar_p], DWORD),
            (
                k,
                "GetVolumeInformationByHandleW",
                [HANDLE, c.c_wchar_p, DWORD, PDWORD, PDWORD, PDWORD, c.c_wchar_p, DWORD],
                BOOL,
            ),
            (
                k,
                "CompareStringOrdinal",
                [c.c_wchar_p, c.c_int32, c.c_wchar_p, c.c_int32, BOOL],
                c.c_int32,
            ),
            (k, "LocalFree", [PVOID], PVOID),
            (a, "OpenThreadToken", [HANDLE, DWORD, BOOL, PHANDLE], BOOL),
            (a, "OpenProcessToken", [HANDLE, DWORD, PHANDLE], BOOL),
            (a, "GetTokenInformation", [HANDLE, c.c_int32, PVOID, DWORD, PDWORD], BOOL),
            (
                a,
                "GetSecurityInfo",
                [HANDLE, c.c_int32, DWORD, PHANDLE, PHANDLE, PHANDLE, PHANDLE, PHANDLE],
                DWORD,
            ),
            (a, "GetSecurityDescriptorLength", [PVOID], DWORD),
            (
                a,
                "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                [c.c_wchar_p, DWORD, PHANDLE, PDWORD],
                BOOL,
            ),
        ]
        for dll, name, args, result in signatures:
            _bind(dll, name, args, result)

    def close(self, value):
        if not self.kernel.CloseHandle(value):
            raise WindowsRuntimeError("runtime_unavailable")

    def free(self, value):
        if self.kernel.LocalFree(value):
            raise WindowsRuntimeError("runtime_unavailable")

    def duplicate(self, value, inheritable):
        result = HANDLE()
        current = self.kernel.GetCurrentProcess()
        if not self.kernel.DuplicateHandle(
            current, value, current, c.byref(result), 0, inheritable, 2
        ):
            raise WindowsRuntimeError("runtime_unavailable")
        return result.value

    def info(self, value, kind, cls):
        result = cls()
        if not self.kernel.GetFileInformationByHandleEx(
            value, kind, c.byref(result), c.sizeof(result)
        ):
            raise WindowsRuntimeError("runtime_unavailable")
        return result
