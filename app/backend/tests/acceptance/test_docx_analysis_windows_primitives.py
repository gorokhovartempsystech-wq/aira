"""C1E1 acceptance: Windows arithmetic, safe capabilities and native reservations."""

import copy
import ctypes as c
import importlib
import os
import pickle
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest


def api():
    return importlib.import_module("ara.docx_analysis_worker.windows")


def part(name):
    return importlib.import_module("ara.docx_analysis_worker.windows." + name)


def reject(code, call):
    with pytest.raises(api().WindowsRuntimeError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code
    assert "sentinel" not in repr(error.value)


@pytest.mark.parametrize("value", [0, 1, 15000, (2**63 - 1) // 1000000])
def test_conversion(value):
    assert api().milliseconds_to_ns(value) == value * 1000000


@pytest.mark.parametrize("value", [True, False, -1, 2**64, 1.0, "1", None])
def test_invalid_conversion(value):
    reject("validation_error", lambda: api().milliseconds_to_ns(value))


@pytest.mark.parametrize("value", [(2**63 - 1) // 1000000 + 1, 2**64 - 1])
def test_conversion_overflow(value):
    reject("clock_unavailable", lambda: api().milliseconds_to_ns(value))


def test_clock_serialized_lazy_and_sticky(monkeypatch):
    clock = part("_clock")
    monkeypatch.setattr(clock.sys, "platform", "win32")
    reads, loads = iter([10, 10, 100000, 9]), []
    monkeypatch.setattr(clock, "_load_clock", lambda: loads.append(1) or (lambda: next(reads)))
    value = api().WindowsClock()
    assert loads == []
    assert [value.now_ns() for _ in range(3)] == [10000000, 10000000, 100000000000]
    reject("clock_unavailable", value.now_ns)
    reject("clock_unavailable", value.now_ns)
    assert loads == [1]
    for copier in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            copier(value)


def test_clock_concurrency_and_platform(monkeypatch):
    module = part("_clock")
    monkeypatch.setattr(module.sys, "platform", "win32")
    count = iter(range(1, 101))
    monkeypatch.setattr(module, "_load_clock", lambda: lambda: next(count))
    clock, out = api().WindowsClock(), []
    threads = [threading.Thread(target=lambda: out.append(clock.now_ns())) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(out) == [n * 1000000 for n in range(1, 31)]
    monkeypatch.setattr(module.sys, "platform", "darwin")
    reject("platform_unavailable", api().WindowsClock().now_ns)


def test_abi_layout():
    a = part("_abi")
    assert c.sizeof(a.DWORD) == c.sizeof(a.BOOL) == 4
    assert c.sizeof(a.WCHAR) == 2
    assert c.sizeof(a.HANDLE) == c.sizeof(a.SIZE_T) == 8
    assert c.sizeof(a.FILE_ID_INFO) == 24
    assert a.FILE_ID_INFO.FileId.offset == 8
    assert c.sizeof(a.FILE_STANDARD_INFO) == 24
    assert a.FILE_STANDARD_INFO.DeletePending.offset == 20
    assert c.sizeof(a.SECURITY_ATTRIBUTES) == 24
    assert a.SECURITY_ATTRIBUTES.lpSecurityDescriptor.offset == 8
    assert a.SECURITY_ATTRIBUTES.bInheritHandle.offset == 16


class FakeFS:
    """Model share=0 file objects, independent opens, duplicates and safe metadata."""

    def __init__(self):
        self.next = 100
        self.handles, self.files, self.calls = {}, {}, []
        self.fail, self.changed = None, None
        self.native = self

    def user(self):
        return "S-1-5-21-11-22-33-1001"

    def _new(self, path):
        self.next += 1
        self.handles[self.next] = path
        return part("_handles").OwnedHandle(self, self.next)

    def directory(self, path, private=False):
        self.calls.append(("directory", path, private))
        return self._new(path)

    def local_ntfs(self, handle, drive):
        if self.fail == "volume":
            raise OSError("sentinel volume")

    def same_name(self, left, right):
        return left.lower() == right.lower()

    def file(self, path, create, sid):
        self.calls.append(("file", path, create))
        if self.fail == "open":
            raise OSError("sentinel open")
        if path in self.handles.values():
            raise api().WindowsRuntimeError("runtime_busy")
        if path not in self.files:
            if not create:
                raise OSError("sentinel missing")
            self.files[path] = len(self.files) + 20
        return self._new(path)

    def inspect(self, handle):
        value = handle.value
        path = self.handles[value]
        if self.fail == "inspect":
            raise OSError("sentinel query")
        directory = path not in self.files
        security = part("_security").Security(
            self.user(),
            True,
            tuple(
                (0, 3 if directory else 0, 0x1F01FF, s)
                for s in (self.user(), "S-1-5-18", "S-1-5-32-544")
            ),
        )
        info = part("_paths").FileInfo(
            (7, (self.files.get(path, len(path))).to_bytes(16, "little")),
            16 if directory else 128,
            0,
            1,
            False,
            path,
            security,
        )
        return self.changed(path, info) if self.changed else info

    def close(self, value):
        self.calls.append(("close", value))
        del self.handles[value]
        if self.fail == "close" or self.fail == ("close", value):
            raise OSError("sentinel close")

    def duplicate(self, value, inheritable):
        self.calls.append(("duplicate", value, inheritable))
        if self.fail == "duplicate":
            raise OSError("sentinel duplicate")
        return self._new(self.handles[value]).detach()


@pytest.fixture
def fs(monkeypatch):
    fs = FakeFS()
    monkeypatch.setattr(part("_locks").sys, "platform", "win32")
    monkeypatch.setattr(part("_paths"), "_load_filesystem", lambda: fs)
    return fs


ROOT = "C:\\Users\\synthetic sentinel\\runtime"


@pytest.mark.parametrize(
    "root",
    [
        None,
        Path("/tmp"),
        "C:",
        "C:\\",
        "C:relative",
        "x",
        "\\\\server\\share",
        "C:/foo",
        "C:\\a\\..\\b",
        "C:\\a\\.\\b",
        "C:\\a\\",
        "C:\\a\\b:stream",
        "C:\\a\\NUL.txt",
        "C:\\a\\LPT¹",
        "C:\\a.\\b",
        "C:\\a ",
        "C:\\a\x00",
        "C:\\a\ud800",
        "C:\\a*",
        "C:\\a\\\\b",
        "C:\\" + "a\\" * 64 + "a",
    ],
)
def test_invalid_root_no_io(fs, root):
    reject("validation_error", lambda: api().acquire_owner(root))
    assert fs.calls == []


def test_owner_slot_capabilities_and_cached_identity(fs):
    owner = api().acquire_owner(ROOT)
    reject("runtime_busy", lambda: api().acquire_owner(ROOT))
    slot = owner.reserve_slot()
    reject("runtime_busy", owner.reserve_slot)
    reject("runtime_busy", owner.close)
    assert type(slot.handle()) is int
    for obj in (slot, owner):
        assert "sentinel" not in repr(obj)
        for copier in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                copier(obj)
    reject("invalid_handle", lambda: owner.release_slot(object()))
    assert owner.release_slot(slot) is True
    reject("invalid_handle", slot.handle)
    fs.files[ROOT + "\\analysis.slot"] += 1
    reject("runtime_unavailable", owner.reserve_slot)
    owner.close()
    owner.close()
    assert not fs.handles


def test_inherited_description_holds_reservation(fs):
    owner = api().acquire_owner(ROOT)
    slot = owner.reserve_slot()
    duplicate = part("_handles").duplicate_slot(slot)
    assert owner.release_slot(slot) is False
    owner.close()
    second = api().acquire_owner(ROOT)
    reject("runtime_busy", second.reserve_slot)
    duplicate.close()
    slot = second.reserve_slot()
    assert second.release_slot(slot) is True
    second.close()
    assert not fs.handles


@pytest.mark.parametrize(
    "field,value",
    [
        ("attributes", 0x400),
        ("attributes", 0x10),
        ("size", 1),
        ("links", 2),
        ("delete_pending", True),
        ("identity", (99, b"x" * 16)),
        ("final_path", ROOT + "\\foreign"),
    ],
)
def test_file_metadata_rejected_without_repair(fs, field, value):
    owner = api().acquire_owner(ROOT)
    fs.changed = lambda path, info: (
        replace(info, **{field: value}) if path.endswith(".slot") else info
    )
    reject("runtime_unavailable", owner.reserve_slot)
    fs.changed = None
    owner.close()
    assert not fs.handles


@pytest.mark.parametrize("change", ["owner", "protected", "extra", "flags", "mask", "type"])
def test_root_acl_rejected(fs, change):
    def corrupt(path, info):
        if path != ROOT:
            return info
        sec = info.security
        if change == "owner":
            sec = replace(sec, owner="S-1-5-21-foreign")
        elif change == "protected":
            sec = replace(sec, protected=False)
        else:
            aces = list(sec.aces)
            if change == "extra":
                aces.append((0, 3, 0x1F01FF, "S-1-1-0"))
            else:
                ace = list(aces[0])
                ace[{"type": 0, "flags": 1, "mask": 2}[change]] = 99
                aces[0] = tuple(ace)
            sec = replace(sec, aces=tuple(aces))
        return replace(info, security=sec)

    fs.changed = corrupt
    reject("runtime_unavailable", lambda: api().acquire_owner(ROOT))
    assert not fs.handles


def test_precheck_failure_and_abandon(fs):
    owner = api().acquire_owner(ROOT)
    slot = owner.reserve_slot()
    raw = slot.handle()
    fs.fail = "inspect"
    reject("runtime_unavailable", lambda: owner.release_slot(slot))
    assert slot.handle() == raw
    owner.abandon()
    owner.abandon()
    assert not fs.handles


def test_close_failure_invalidates_before_syscall(fs):
    owner = api().acquire_owner(ROOT)
    slot = owner.reserve_slot()
    value = slot.handle()
    fs.fail = ("close", value)
    reject("runtime_unavailable", lambda: owner.release_slot(slot))
    reject("invalid_handle", slot.handle)
    fs.fail = None
    owner.abandon()
    assert [call for call in fs.calls if call == ("close", value)] == [("close", value)]
    assert not fs.handles


def test_import_inert_fresh_process():
    source = str(Path(__file__).resolve().parents[2] / "src")
    script = f"""
import sys, ctypes, os, threading, subprocess
sys.path.insert(0, {source!r})
def denied(*a, **k): raise AssertionError('unexpected IO')
ctypes.CDLL = denied
ctypes.WinDLL = denied
os.getenv = denied
subprocess.Popen = denied
threading.Thread.start = denied
import ara.docx_analysis_worker.windows as w
w.WindowsClock()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script], capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode()


@pytest.fixture
def native():
    if sys.platform != "win32":
        pytest.skip("native Windows NTFS/HANDLE acceptance pending")


@pytest.fixture
def native_root(native, tmp_path):
    module = part("_paths")
    fs = module._load_filesystem()
    path = str(tmp_path / "synthetic sentinel")
    # Root setup is test-only. Production acquire never creates directories.
    kernel = fs.native.kernel
    create = kernel.CreateDirectoryW
    create.argtypes = [c.c_wchar_p, c.POINTER(part("_abi").SECURITY_ATTRIBUTES)]
    create.restype = part("_abi").BOOL
    with part("_security").descriptor(fs.native, fs.user(), directory=True) as sa:
        assert create(path, c.byref(sa))
    return path


def test_native_reservations_and_handle_stability(native_root):
    kernel = part("_paths")._load_filesystem().native.kernel
    count = kernel.GetProcessHandleCount
    count.argtypes = [c.c_void_p, c.POINTER(c.c_uint32)]
    count.restype = c.c_int32
    before, after = c.c_uint32(), c.c_uint32()
    assert count(kernel.GetCurrentProcess(), c.byref(before))
    owner = api().acquire_owner(native_root)
    reject("runtime_busy", lambda: api().acquire_owner(native_root))
    clock = api().WindowsClock()
    assert clock.now_ns() <= clock.now_ns()
    for _ in range(100):
        slot = owner.reserve_slot()
        assert owner.release_slot(slot) is True
    owner.close()
    assert count(kernel.GetCurrentProcess(), c.byref(after))
    assert after.value == before.value
    assert (Path(native_root) / "runtime.owner").read_bytes() == b""
    assert (Path(native_root) / "analysis.slot").read_bytes() == b""


def test_native_inherited_slot(native_root):
    owner = api().acquire_owner(native_root)
    slot = owner.reserve_slot()
    duplicate = part("_handles").duplicate_slot(slot)
    startup = subprocess.STARTUPINFO()
    startup.lpAttributeList = {"handle_list": [duplicate.value]}
    script = (
        "import sys,os,threading; "
        "threading.Timer(5,os._exit,args=(99,)).start(); "
        "print('ready',flush=True); sys.stdin.readline(); os._exit(0)"
    )
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        startupinfo=startup,
        close_fds=True,
    )
    duplicate.close()
    second = None
    try:
        assert child.stdout.readline() == b"ready\r\n"
        assert owner.release_slot(slot) is False
        owner.close()
        second = api().acquire_owner(native_root)
        reject("runtime_busy", second.reserve_slot)
        child.communicate(b"done\n", timeout=5)
        assert child.returncode == 0
        assert second.release_slot(second.reserve_slot()) is True
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        if second:
            second.abandon()
        owner.abandon()


@pytest.mark.parametrize("kind", ["hardlink", "nonempty", "acl"])
def test_native_unsafe_existing_files(native_root, kind):
    owner = api().acquire_owner(native_root)
    slot = owner.reserve_slot()
    assert owner.release_slot(slot)
    owner.close()
    path = Path(native_root) / "analysis.slot"
    if kind == "hardlink":
        os.link(path, Path(native_root) / "other")
    elif kind == "nonempty":
        path.write_bytes(b"synthetic")
    else:
        path.unlink()
        path.write_bytes(b"")  # inherited unprotected DACL must be rejected
    owner = api().acquire_owner(native_root)
    try:
        reject("runtime_unavailable", owner.reserve_slot)
    finally:
        owner.abandon()
