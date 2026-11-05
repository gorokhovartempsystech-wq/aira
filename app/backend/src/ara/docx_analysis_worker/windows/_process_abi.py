"""Explicit Win64 Job/process bindings. Import performs no native initialization."""

import ctypes as c
import subprocess
import time

from ._abi import BOOL, DWORD, HANDLE, PVOID, SIZE_T, WORD, _bind
from ._errors import WindowsRuntimeError
from ._handles import OwnedHandle
from ._io_abi import IO


class STARTUPINFOW(c.Structure):
    _fields_ = (
        [("cb", DWORD), ("lpReserved", PVOID), ("lpDesktop", PVOID), ("lpTitle", PVOID)]
        + [
            (n, DWORD)
            for n in (
                "dwX",
                "dwY",
                "dwXSize",
                "dwYSize",
                "dwXCountChars",
                "dwYCountChars",
                "dwFillAttribute",
                "dwFlags",
            )
        ]
        + [
            ("wShowWindow", WORD),
            ("cbReserved2", WORD),
            ("lpReserved2", PVOID),
            ("hStdInput", HANDLE),
            ("hStdOutput", HANDLE),
            ("hStdError", HANDLE),
        ]
    )


class STARTUPINFOEXW(c.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", PVOID)]


class PROCESS_INFORMATION(c.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


class BASIC_LIMIT_INFORMATION(c.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", c.c_int64),
        ("PerJobUserTimeLimit", c.c_int64),
        ("LimitFlags", DWORD),
        ("MinimumWorkingSetSize", SIZE_T),
        ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD),
        ("Affinity", SIZE_T),
        ("PriorityClass", DWORD),
        ("SchedulingClass", DWORD),
    ]


class IO_COUNTERS(c.Structure):
    _fields_ = [
        (n, c.c_uint64)
        for n in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class EXTENDED_LIMIT_INFORMATION(c.Structure):
    _fields_ = [("BasicLimitInformation", BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS)] + [
        (n, SIZE_T)
        for n in (
            "ProcessMemoryLimit",
            "JobMemoryLimit",
            "PeakProcessMemoryUsed",
            "PeakJobMemoryUsed",
        )
    ]


class BASIC_ACCOUNTING_INFORMATION(c.Structure):
    _fields_ = [
        (n, c.c_int64)
        for n in (
            "TotalUserTime",
            "TotalKernelTime",
            "ThisPeriodTotalUserTime",
            "ThisPeriodTotalKernelTime",
        )
    ] + [
        (n, DWORD)
        for n in (
            "TotalPageFaultCount",
            "TotalProcesses",
            "ActiveProcesses",
            "TotalTerminatedProcesses",
        )
    ]


def utf16(text):
    if type(text) is not str or "\0" in text:
        raise WindowsRuntimeError("validation_error")
    try:
        raw = text.encode("utf-16-le") + b"\0\0"
        if len(raw) > 65534:
            raise ValueError()
        return c.create_string_buffer(raw)
    except Exception:
        raise WindowsRuntimeError("validation_error") from None


class ProcessAPI:
    def __init__(self):
        self.io = IO()
        self.kernel = k = self.io.kernel
        for name, args, result in [
            ("CreateJobObjectW", [PVOID, PVOID], HANDLE),
            ("SetInformationJobObject", [HANDLE, c.c_int32, PVOID, DWORD], BOOL),
            ("QueryInformationJobObject", [HANDLE, c.c_int32, PVOID, DWORD, PVOID], BOOL),
            ("IsProcessInJob", [HANDLE, HANDLE, c.POINTER(BOOL)], BOOL),
            ("TerminateJobObject", [HANDLE, DWORD], BOOL),
            ("InitializeProcThreadAttributeList", [PVOID, DWORD, DWORD, c.POINTER(SIZE_T)], BOOL),
            (
                "UpdateProcThreadAttribute",
                [PVOID, DWORD, SIZE_T, PVOID, SIZE_T, PVOID, PVOID],
                BOOL,
            ),
            ("DeleteProcThreadAttributeList", [PVOID], None),
            (
                "CreateProcessW",
                [
                    PVOID,
                    PVOID,
                    PVOID,
                    PVOID,
                    BOOL,
                    DWORD,
                    PVOID,
                    PVOID,
                    c.POINTER(STARTUPINFOEXW),
                    c.POINTER(PROCESS_INFORMATION),
                ],
                BOOL,
            ),
            ("ResumeThread", [HANDLE], DWORD),
            ("GetExitCodeProcess", [HANDLE, c.POINTER(DWORD)], BOOL),
            ("TerminateProcess", [HANDLE, DWORD], BOOL),
            ("SetHandleInformation", [HANDLE, DWORD, DWORD], BOOL),
            ("GetWindowsDirectoryW", [PVOID, DWORD], DWORD),
            ("GetNamedPipeInfo", [HANDLE, PVOID, PVOID, PVOID, PVOID], BOOL),
            ("WaitForMultipleObjects", [DWORD, c.POINTER(HANDLE), BOOL, DWORD], DWORD),
        ]:
            _bind(k, name, args, result)

    @staticmethod
    def require(ok):
        if not ok:
            raise WindowsRuntimeError("runtime_unavailable")

    def close(self, value):
        self.io.close(value)

    def duplicate_rights(self, value, rights=None):
        out, process = HANDLE(), self.kernel.GetCurrentProcess()
        self.require(
            self.kernel.DuplicateHandle(
                process,
                value,
                process,
                c.byref(out),
                0 if rights is None else rights,
                True,
                2 if rights is None else 0,
            )
        )
        return OwnedHandle(self, out.value)

    def new_job(self, limit):
        handle = OwnedHandle(self, self.kernel.CreateJobObjectW(None, None))
        try:
            info = EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x2008
            info.BasicLimitInformation.ActiveProcessLimit = limit
            self.require(
                self.kernel.SetInformationJobObject(handle.value, 9, c.byref(info), c.sizeof(info))
            )
            return handle.detach()
        finally:
            handle.close()

    def job_limits(self, value):
        info = EXTENDED_LIMIT_INFORMATION()
        self.require(
            self.kernel.QueryInformationJobObject(value, 9, c.byref(info), c.sizeof(info), None)
        )
        return info.BasicLimitInformation.LimitFlags, info.BasicLimitInformation.ActiveProcessLimit

    def job_count(self, value):
        info = BASIC_ACCOUNTING_INFORMATION()
        self.require(
            self.kernel.QueryInformationJobObject(value, 1, c.byref(info), c.sizeof(info), None)
        )
        return info.ActiveProcesses

    def terminate_job(self, value):
        self.require(self.kernel.TerminateJobObject(value, 74))

    def terminate_process(self, value):
        self.require(self.kernel.TerminateProcess(value, 74))

    def in_job(self, process, job):
        result = BOOL()
        self.require(self.kernel.IsProcessInJob(process, job, c.byref(result)))
        return bool(result.value)

    def resume(self, thread):
        return self.kernel.ResumeThread(thread)

    def process_exit(self, process):
        if not self.io.wait_event(process, 0):
            return None
        result = DWORD()
        self.require(self.kernel.GetExitCodeProcess(process, c.byref(result)))
        return result.value

    def clear_inherit(self, value):
        self.require(self.kernel.SetHandleInformation(value, 1, 0))

    def nul(self, write=False):
        return OwnedHandle(
            self,
            self.kernel.CreateFileW(
                "NUL", 0x40000000 if write else 0x80000000, 3, None, 3, 0, None
            ),
        )

    def windows_directory(self):
        buffer = c.create_string_buffer(65536)
        length = self.kernel.GetWindowsDirectoryW(buffer, 32768)
        self.require(0 < length < 32768)
        return buffer.raw[: length * 2].decode("utf-16-le")

    def wait(self, handles, timeout=100):
        if not 0 <= timeout <= 100 or len(handles) > 32 or len(set(handles)) != len(handles):
            raise WindowsRuntimeError("validation_error")
        if not handles:
            time.sleep(timeout / 1000)
            return
        result = self.kernel.WaitForMultipleObjects(
            len(handles), (HANDLE * len(handles))(*handles), False, timeout
        )
        self.require(result == 258 or 0 <= result < len(handles))

    def launch(self, record, config, job, handles, stdio):
        """Capture returned capabilities BEFORE deleting attribute storage."""
        size = SIZE_T()
        initialized = False
        storage = None
        try:
            probe = self.kernel.InitializeProcThreadAttributeList(None, 2, 0, c.byref(size))
            self.require(not probe and c.get_last_error() == 122)
            self.require(0 < size.value <= 65536)
            storage = c.create_string_buffer(size.value)
            record._storage = [storage]
            self.require(
                self.kernel.InitializeProcThreadAttributeList(storage, 2, 0, c.byref(size))
            )
            initialized = True
            jobs, inherited = (HANDLE * 1)(job), (HANDLE * len(handles))(*handles)
            record._storage += [jobs, inherited]
            for attr, values in [(0x2000D, jobs), (0x20002, inherited)]:
                self.require(
                    self.kernel.UpdateProcThreadAttribute(
                        storage, 0, attr, values, c.sizeof(values), None, None
                    )
                )
            exe, argv, cwd, env = config
            app, cmd, directory = utf16(exe), utf16(subprocess.list2cmdline(argv)), utf16(cwd)
            environment = c.create_string_buffer(
                ("\0".join(k + "=" + v for k, v in sorted(env.items())) + "\0\0").encode(
                    "utf-16-le"
                )
            )
            si, pi = STARTUPINFOEXW(), PROCESS_INFORMATION()
            si.StartupInfo.cb, si.StartupInfo.dwFlags = c.sizeof(si), 0x100
            si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = stdio
            si.lpAttributeList = c.addressof(storage)
            record._storage += [app, cmd, directory, environment, si, pi]
            # No native call has been made before this boundary.
            record.creation = "unknown"
            ok = self.kernel.CreateProcessW(
                app,
                cmd,
                None,
                None,
                True,
                0x08080404,
                environment,
                directory,
                c.byref(si),
                c.byref(pi),
            )
            record.capture(bool(ok), pi.hProcess, pi.hThread)
        except BaseException:
            if record.creation == "not_started":
                record.capture(False, 0, 0)
            raise
        finally:
            if initialized:
                self.kernel.DeleteProcThreadAttributeList(storage)
            record._storage = None


def _load_api():
    return ProcessAPI()
