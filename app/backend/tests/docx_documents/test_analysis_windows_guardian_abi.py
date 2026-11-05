"""Observe raw call arguments/storage lifetimes without emulating Windows success."""

import ctypes as c
import importlib
import subprocess
import sys
from pathlib import Path

import pytest


def part(name):
    return importlib.import_module("ara.docx_analysis_worker.windows." + name)


class Function:
    def __init__(self, name, kernel):
        self.name, self.kernel = name, kernel

    def __call__(self, *args):
        self.kernel.calls.append((self.name, args))
        return self.kernel.handlers.get(self.name, lambda *a: 1)(*args)


class Kernel:
    def __init__(self):
        self.functions, self.handlers, self.calls = {}, {}, []

    def __getattr__(self, name):
        return self.functions.setdefault(name, Function(name, self))


@pytest.fixture
def abi(monkeypatch):
    m, kernel = part("_process_abi"), Kernel()

    class IO:
        def __init__(self):
            self.kernel = kernel

        def close(self, handle):
            kernel.CloseHandle(handle)

        def wait_event(self, handle, timeout):
            result = kernel.WaitForSingleObject(handle, timeout)
            if result not in (0, 258):
                raise part("_errors").WindowsRuntimeError()
            return result == 0

    monkeypatch.setattr(m, "IO", IO)
    monkeypatch.setattr(c, "get_last_error", lambda: 122, raising=False)
    return m, m.ProcessAPI(), kernel


def test_signatures_and_creation_attributes_retained_until_capture(abi):
    m, api, kernel = abi
    observed = []

    def initialize(storage, count, flags, size):
        assert count == 2 and flags == 0
        c.cast(size, c.POINTER(c.c_size_t)).contents.value = 128
        return bool(storage)

    def update(storage, flags, attribute, values, size, previous, returned):
        assert flags == 0 and previous is None and returned is None
        array = c.cast(values, c.POINTER(c.c_void_p))
        observed.append((attribute, [array[n] for n in range(size // 8)]))
        return 1

    class Record:
        creation = "not_started"
        _storage = None

        def capture(self, ok, process, thread):
            assert kernel.calls[-1][0] == "CreateProcessW"
            assert self._storage and (ok, process, thread) == (True, 20, 21)
            self.creation = "created"

    record = Record()

    def create(app, cmd, process_sa, thread_sa, inherit, flags, env, cwd, si, pi):
        assert process_sa is thread_sa is None and inherit is True and flags == 0x08080404
        start = c.cast(si, c.POINTER(m.STARTUPINFOEXW)).contents
        assert start.StartupInfo.cb == 112 and start.StartupInfo.dwFlags == 0x100
        assert (
            start.StartupInfo.hStdInput,
            start.StartupInfo.hStdOutput,
            start.StartupInfo.hStdError,
        ) == (30, 31, 31)
        assert b"S\x00y\x00s\x00t\x00e\x00m\x00R\x00o\x00o\x00t\x00" in env.raw
        assert env.raw[:-1].decode("utf-16-le").endswith("\0\0")
        result = c.cast(pi, c.POINTER(m.PROCESS_INFORMATION)).contents
        result.hProcess, result.hThread = 20, 21
        return 1

    kernel.handlers.update(
        InitializeProcThreadAttributeList=initialize,
        UpdateProcThreadAttribute=update,
        CreateProcessW=create,
    )
    api.launch(
        record,
        (
            r"C:\Program Files\python.exe",
            [r"C:\Program Files\python.exe", "-I", "кириллица"],
            r"C:\trusted",
            {"SystemRoot": r"C:\Windows", "WINDIR": r"C:\Windows"},
        ),
        10,
        (30, 31),
        (30, 31, 31),
    )
    assert observed == [(0x2000D, [10]), (0x20002, [30, 31])]
    assert record.creation == "created" and record._storage is None
    assert kernel.calls[-1][0] == "DeleteProcThreadAttributeList"
    assert kernel.CreateProcessW.argtypes[5] is m.DWORD
    assert kernel.ResumeThread.restype is m.DWORD
    assert kernel.DeleteProcThreadAttributeList.restype is None


@pytest.mark.parametrize("phase", ["initialize", "attribute", "create"])
def test_raw_failure_before_create_is_known_not_created(abi, phase):
    m, api, kernel = abi

    class Record:
        creation = "not_started"
        _storage = None

        def capture(self, ok, p, t):
            assert not ok
            self.creation = "failed"

    rec = Record()

    def initialize(storage, count, flags, size):
        c.cast(size, c.POINTER(c.c_size_t)).contents.value = 128
        return bool(storage) and phase != "initialize"

    kernel.handlers["InitializeProcThreadAttributeList"] = initialize
    kernel.handlers["UpdateProcThreadAttribute"] = lambda *args: phase != "attribute"
    kernel.handlers["CreateProcessW"] = lambda *args: 0
    if phase == "create":
        api.launch(rec, ("python.exe", ["python.exe"], "C:\\", {}), 10, (30,), (30, 30, 30))
    else:
        with pytest.raises(part("_errors").WindowsRuntimeError):
            api.launch(rec, ("python.exe", ["python.exe"], "C:\\", {}), 10, (30,), (30, 30, 30))
    assert rec.creation == "failed"
    names = [name for name, _ in kernel.calls]
    assert names.count("DeleteProcThreadAttributeList") == (phase != "initialize")


def test_reduced_rights_duplicate_is_not_same_access(abi):
    _, api, kernel = abi

    def duplicate(source, handle, target, out, access, inherit, options):
        assert handle == 99 and access == 0x100000 and inherit is True and options == 0
        c.cast(out, c.POINTER(c.c_void_p)).contents.value = 100
        return 1

    kernel.handlers["DuplicateHandle"] = duplicate
    duplicate = api.duplicate_rights(99, 0x100000)
    duplicate.close()
    assert kernel.calls[-1] == ("CloseHandle", (100,))


@pytest.mark.parametrize("outcome", [0, 258, 0xFFFFFFFF])
def test_wait_before_exit_code_query(abi, outcome):
    _, api, kernel = abi
    kernel.handlers["WaitForSingleObject"] = lambda *a: outcome
    if outcome == 0xFFFFFFFF:
        with pytest.raises(part("_errors").WindowsRuntimeError):
            api.process_exit(20)
    else:
        assert api.process_exit(20) == (0 if outcome == 0 else None)
    assert any(n == "GetExitCodeProcess" for n, a in kernel.calls) is (outcome == 0)


def test_new_modules_inert_in_fresh_process():
    source = str(Path(__file__).parents[2] / "src")
    names = (
        "_process_abi _jobs _spawn _adopt _launch _bootstrap _guardian _guardian_entry "
        "_child_bootstrap _child_entry _fixture_child"
    ).split()
    program = (
        "import sys,ctypes,importlib;sys.path.insert(0,sys.argv[1]);"
        "ctypes.WinDLL=lambda *a,**k:(_ for _ in ()).throw(AssertionError('native on import'));"
        "[importlib.import_module('ara.docx_analysis_worker.windows.'+name) "
        "for name in sys.argv[2:]]"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", program, source, *names], capture_output=True, timeout=5
    )
    assert result.returncode == 0 and result.stdout == result.stderr == b""
