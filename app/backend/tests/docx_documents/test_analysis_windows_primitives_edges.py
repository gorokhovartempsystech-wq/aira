"""Additional ABI, allocation, identity and failure-path checks for C1E1."""

import ctypes as c
import importlib.util
import os
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ara.docx_analysis_worker import windows as w
from ara.docx_analysis_worker.windows import _abi as a
from ara.docx_analysis_worker.windows import _clock, _handles, _locks, _paths, _security

spec = importlib.util.spec_from_file_location(
    "windows_acceptance_support",
    Path(__file__).parents[1] / "acceptance/test_docx_analysis_windows_primitives.py",
)
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)
native, native_root = support.native, support.native_root


@pytest.fixture
def fs(monkeypatch):
    fake = support.FakeFS()
    monkeypatch.setattr(_locks.sys, "platform", "win32")
    monkeypatch.setattr(_paths, "_load_filesystem", lambda: fake)
    return fake


def rejects(call, code="runtime_unavailable"):
    with pytest.raises(w.WindowsRuntimeError) as exc:
        call()
    assert exc.value.code == code
    assert "sentinel" not in str(exc.value)


def test_foreign_and_forged_handles_and_sticky_slot_identity(fs, monkeypatch):
    owner = w.acquire_owner(support.ROOT)
    slot = owner.reserve_slot()
    fake = object.__new__(_locks.SlotLease)
    for attr in slot.__slots__:
        setattr(fake, attr, getattr(slot, attr))
    rejects(fake.handle, "invalid_handle")
    rejects(lambda: _handles.duplicate_slot(fake), "invalid_handle")
    pid = os.getpid()
    monkeypatch.setattr(_locks.os, "getpid", lambda: pid + 1)
    rejects(slot.handle, "invalid_handle")
    monkeypatch.setattr(_locks.os, "getpid", lambda: pid)
    assert owner.release_slot(slot)
    del fs.files[support.ROOT + "\\analysis.slot"]
    rejects(owner.reserve_slot)
    assert support.ROOT + "\\analysis.slot" not in fs.files
    owner.abandon()


@pytest.mark.parametrize("fail", ["inspect", "volume", "open"])
def test_failed_acquire_closes_all_pins(fs, fail):
    fs.fail = fail
    rejects(lambda: w.acquire_owner(support.ROOT))
    assert not fs.handles


def test_failed_post_close_probe_is_not_success(fs):
    owner = w.acquire_owner(support.ROOT)
    slot = owner.reserve_slot()
    close = fs.close
    value = slot.handle()

    def fail_next(value_to_close):
        close(value_to_close)
        if value_to_close == value:
            fs.fail = "open"

    fs.close = fail_next
    rejects(lambda: owner.release_slot(slot))
    rejects(slot.handle, "invalid_handle")
    owner.abandon()
    assert not fs.handles


def test_close_error_does_not_retry_reused_number():
    calls = []

    def bad(value):
        calls.append(value)
        raise OSError("sentinel")

    native = SimpleNamespace(close=bad)
    handle = _handles.OwnedHandle(native, 123)
    rejects(handle.close)
    handle.close()
    assert calls == [123]
    rejects(lambda: handle.value, "invalid_handle")


@pytest.mark.parametrize("number", [None, 0, -1, 2**64 - 1, True])
def test_invalid_native_handle(number):
    rejects(lambda: _handles.OwnedHandle(None, number))


def sid(text):
    values = [int(v) for v in text.split("-")[1:]]
    return (
        bytes((values[0], len(values) - 2))
        + values[1].to_bytes(6, "big")
        + b"".join(struct.pack("<I", v) for v in values[2:])
    )


def sd(directory=False):
    user = sid("S-1-5-21-11-22-33-1001")
    aces = []
    for text in ("S-1-5-21-11-22-33-1001", "S-1-5-18", "S-1-5-32-544"):
        identity = sid(text)
        aces.append(
            struct.pack("<BBHI", 0, 3 if directory else 0, len(identity) + 8, 0x1F01FF) + identity
        )
    acl = struct.pack("<BBHHH", 2, 0, 8 + sum(map(len, aces)), 3, 0) + b"".join(aces)
    return struct.pack("<BBHIIII", 1, 0, 0x9004, 20, 0, 0, 20 + len(user)) + user + acl


def test_binary_security_roundtrip():
    for directory in (True, False):
        info = _security.decode_security(sd(directory))
        _security.require_private(info, info.owner, directory)
        rejects(
            lambda: _security.require_private(replace(info, protected=False), info.owner, directory)
        )


@pytest.mark.parametrize("cut", [0, 1, 8, 19, 20, 35, 47, 60, 80, 100])
def test_truncated_security_descriptor(cut):
    rejects(lambda: _security.decode_security(sd()[:cut]))


class Raw:
    """Native ABI-shaped functions with real allocated descriptor buffers."""

    def __init__(self, monkeypatch):
        self.calls, self.buffers, self.failure = [], [], None
        monkeypatch.setattr(c, "get_last_error", lambda: self.failure or 0, raising=False)
        self.kernel = SimpleNamespace(
            CreateFileW=self.create,
            LocalFree=self.free,
            GetFinalPathNameByHandleW=self.path,
            GetDriveTypeW=lambda path: 3,
            GetVolumeInformationByHandleW=self.volume,
        )
        self.security = SimpleNamespace(
            ConvertStringSecurityDescriptorToSecurityDescriptorW=self.descriptor,
            GetSecurityInfo=self.security_info,
            GetSecurityDescriptorLength=lambda ptr: len(sd()),
        )

    def alloc(self, out):
        buf = c.create_string_buffer(sd())
        self.buffers.append(buf)
        c.cast(out, c.POINTER(c.c_void_p))[0] = c.addressof(buf)

    def descriptor(self, text, revision, out, size):
        self.calls.append(("descriptor", text))
        self.alloc(out)
        return 1

    def security_info(self, value, kind, flags, *outputs):
        assert kind == 1 and flags == 5
        self.alloc(outputs[-1])
        return self.failure or 0

    def free(self, value):
        self.calls.append(("free", value))
        if self.failure == "free":
            raise OSError("sentinel free")
        self.buffers.clear()

    def create(self, path, access, share, attributes, disposition, flags, template):
        self.calls.append(("create", access, share, disposition, flags))
        if attributes is not None:
            assert attributes._obj.bInheritHandle == 0
        return 2**64 - 1 if type(self.failure) is int else 555

    def close(self, value):
        self.calls.append(("close", value))

    def path(self, value, buffer, size, flags):
        if self.failure == "huge":
            return 40000
        if self.failure == "resize" and size == 512:
            return 700
        buffer.value = "\\\\?\\C:\\Users\\synthetic sentinel\\runtime"
        return len(buffer.value)

    def volume(self, handle, label, size, serial, maximum, flags, filesystem, capacity):
        filesystem.value = "ReFS" if self.failure == "filesystem" else "NTFS"
        return 1


@pytest.fixture
def raw_fs(monkeypatch):
    raw = Raw(monkeypatch)
    monkeypatch.setattr(_paths, "Native", lambda: raw)
    return raw, _paths.NativeFilesystem()


def test_native_open_flags_and_allocation_cleanup(raw_fs):
    raw, fs = raw_fs
    directory = fs.directory(support.ROOT, private=True)
    directory.close()
    assert ("create", 0x20080, 1, 3, 0x2200000) in raw.calls
    handle = fs.file(support.ROOT + "\\analysis.slot", False, "S-1-5-21-11-22-33-1001")
    assert ("create", 0xC0020000, 0, 3, 0x200000) in raw.calls
    handle.close()
    assert len([x for x in raw.calls if x[0] == "free"]) == 1
    assert not raw.buffers


@pytest.mark.parametrize(
    "error,code", [(32, "runtime_busy"), (5, "runtime_unavailable"), (2, "runtime_unavailable")]
)
def test_raw_create_failure_and_no_descriptor_leak(raw_fs, error, code):
    raw, fs = raw_fs
    raw.failure = error
    rejects(lambda: fs.file(support.ROOT, True, "S-1-5-18"), code)
    assert not raw.buffers


def test_descriptor_free_failure_closes_created_handle(raw_fs):
    raw, fs = raw_fs
    raw.failure = "free"
    with pytest.raises(OSError):
        fs.file(support.ROOT, True, "S-1-5-18")
    assert ("close", 555) in raw.calls


def test_security_read_and_allocated_error_cleanup(raw_fs):
    raw, _ = raw_fs
    result = _security.read_security(raw, 555)
    assert result.owner == "S-1-5-21-11-22-33-1001"
    raw.failure = 5
    rejects(lambda: _security.read_security(raw, 555))
    assert not raw.buffers
    assert len([x for x in raw.calls if x[0] == "free"]) == 2


def test_final_path_and_bounded_resize(raw_fs):
    raw, fs = raw_fs
    assert fs.final_path(1) == support.ROOT
    raw.failure = "resize"
    assert fs.final_path(1) == support.ROOT
    raw.failure = "huge"
    rejects(lambda: fs.final_path(1))
    raw.failure = "filesystem"
    rejects(lambda: fs.local_ntfs(SimpleNamespace(value=555), "C:\\"))


def test_binding_signatures_and_system_search(monkeypatch):
    libraries = []

    class Function:
        def __call__(self, *args):
            return 1

    class DLL:
        def __getattr__(self, name):
            fn = Function()
            setattr(self, name, fn)
            return fn

    def load(name, **kwargs):
        assert kwargs == {"use_last_error": True, "winmode": 0x800}
        dll = DLL()
        libraries.append((name, dll))
        return dll

    monkeypatch.setattr(a.sys, "platform", "win32")
    monkeypatch.setattr(c, "WinDLL", load, raising=False)
    n = a.Native()
    assert [name for name, dll in libraries] == ["kernel32.dll", "advapi32.dll"]
    assert n.kernel.CreateFileW.restype is a.HANDLE
    assert n.security.GetSecurityInfo.restype is a.DWORD
    assert n.kernel.CloseHandle.restype is a.BOOL
    read = _clock._load_clock()
    assert read.restype is a.DWORD64 and read.argtypes == []


def test_native_reparse_root(native_root):
    alias = Path(native_root).parent / "alias"
    try:
        os.symlink(native_root, alias, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("native symlink privilege unavailable; reparse gate pending")
        raise
    try:
        rejects(lambda: w.acquire_owner(str(alias)))
    finally:
        alias.unlink()


def test_native_abrupt_owner_keeps_inherited_slot(native_root):
    # Child lasts at most five seconds even if the test or its parent dies.
    source = str(Path(__file__).resolve().parents[2] / "src")
    program = f"""
import sys,subprocess,os
sys.path.insert(0,{source!r})
from ara.docx_analysis_worker import windows as w
from ara.docx_analysis_worker.windows._handles import duplicate_slot
owner=w.acquire_owner({native_root!r})
slot=owner.reserve_slot()
h=duplicate_slot(slot)
si=subprocess.STARTUPINFO()
si.lpAttributeList={{'handle_list':[h.value]}}
child=subprocess.Popen([sys.executable,'-I','-B','-c',
 'import time; print(\"ready\",flush=True); time.sleep(5)'],
 stdout=subprocess.PIPE,startupinfo=si,close_fds=True)
h.close()
assert child.stdout.readline().strip()==b'ready'
print('ready',flush=True)
os._exit(0)
"""
    parent = subprocess.run(
        [sys.executable, "-I", "-B", "-c", program], capture_output=True, timeout=4
    )
    assert parent.returncode == 0 and parent.stdout.strip() == b"ready"
    owner = w.acquire_owner(native_root)
    try:
        rejects(owner.reserve_slot, "runtime_busy")
        import time

        end = time.monotonic() + 7
        while True:
            try:
                slot = owner.reserve_slot()
                break
            except w.WindowsRuntimeError as exc:
                assert exc.code == "runtime_busy" and time.monotonic() < end
                time.sleep(0.05)
        assert owner.release_slot(slot)
    finally:
        owner.abandon()


@pytest.mark.parametrize(
    "fault", ["thread_token", "thread_error", "process_token", "size", "read", "sid"]
)
def test_token_query_failure_closes_only_issued_token(monkeypatch, fault):
    raw = Raw(monkeypatch)
    raw.failure = 1008
    token, buffer_holder = 812, []
    raw.kernel.GetCurrentThread = lambda: 22
    raw.kernel.GetCurrentProcess = lambda: 11

    def set_token(pointer):
        c.cast(pointer, c.POINTER(c.c_void_p))[0] = token
        return 1

    def thread(handle, access, own, out):
        if fault == "thread_token":
            return set_token(out)
        if fault == "thread_error":
            raw.failure = 5
        return 0

    def process(handle, access, out):
        return 0 if fault == "process_token" else set_token(out)

    def information(handle, kind, data, capacity, out):
        if not data:
            raw.failure = 122
            c.cast(out, c.POINTER(c.c_uint32))[0] = 16 if fault == "size" else 64
            return 0
        if fault == "read":
            return 0
        address = c.cast(data, c.c_void_p).value
        identity = sid("S-1-5-21-11-22-33-1001")
        c.cast(data, c.POINTER(c.c_void_p))[0] = address + (99 if fault == "sid" else 16)
        if capacity == 16:
            return 1
        c.memmove(address + 16, identity, len(identity))
        buffer_holder.append(data)
        return 1

    raw.security.OpenThreadToken = thread
    raw.security.OpenProcessToken = process
    raw.security.GetTokenInformation = information
    monkeypatch.setattr(_paths, "Native", lambda: raw)
    fs = _paths.NativeFilesystem()
    if fault == "size":
        # Small buffer is rejected by bounded SID parsing, not read out-of-bounds.
        rejects(fs.user)
    else:
        rejects(fs.user)
    closed = [v for name, v in raw.calls if name == "close"]
    assert closed == ([] if fault in ("thread_error", "process_token") else [token])


def test_native_close_duplicate_and_error_semantics(monkeypatch):
    raw = Raw(monkeypatch)
    n = object.__new__(a.Native)
    n.kernel = raw.kernel
    raw.kernel.CloseHandle = lambda value: 0
    rejects(lambda: n.close(999))
    raw.kernel.GetCurrentProcess = lambda: 55

    def duplicate(source, value, target, out, access, inherit, flags):
        assert source == target == 55 and access == 0 and flags == 2 and inherit
        c.cast(out, c.POINTER(c.c_void_p))[0] = 777
        return 1

    raw.kernel.DuplicateHandle = duplicate
    assert n.duplicate(666, True) == 777
    raw.kernel.DuplicateHandle = lambda *args: 0
    rejects(lambda: n.duplicate(666, False))


def test_clock_load_failure_and_overflow_sticky(monkeypatch):
    monkeypatch.setattr(_clock.sys, "platform", "win32")
    for loader in (lambda: (_ for _ in ()).throw(OSError("sentinel")), lambda: lambda: 2**64 - 1):
        monkeypatch.setattr(_clock, "_load_clock", loader)
        clock = w.WindowsClock()
        rejects(clock.now_ns, "clock_unavailable")
        monkeypatch.setattr(_clock, "_load_clock", lambda: lambda: 1)
        rejects(clock.now_ns, "clock_unavailable")
