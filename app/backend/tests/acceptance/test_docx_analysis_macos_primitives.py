"""C1D1 frozen contract: independent clock arithmetic and native lifetime locks."""

import copy
import ctypes
import importlib
import os
import pickle
import select
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import pytest


def api():
    return importlib.import_module("ara.docx_analysis_worker.macos")


def reject(code, call):
    with pytest.raises(api().MacRuntimeError) as exc:
        call()
    assert exc.value.code == code
    assert "private-sentinel" not in "".join(traceback.format_exception(exc.value))


@pytest.fixture
def root(tmp_path):
    p = tmp_path.resolve() / "private-sentinel"
    p.mkdir(mode=0o700)
    return p


@pytest.fixture
def native():
    if sys.platform != "darwin":
        pytest.skip("native Darwin acceptance required")


@pytest.mark.parametrize(
    "ticks,numer,denom,expected",
    [
        (0, 1, 1, 0),
        (1, 125, 3, 41),
        (3, 125, 3, 125),
        (2**63 - 1, 1, 1, 2**63 - 1),
        (2**64 - 1, 1, 3, (2**64 - 1) // 3),
    ],
)
def test_exact_integer_conversion(ticks, numer, denom, expected):
    assert api().ticks_to_ns(ticks, numer, denom) == expected


@pytest.mark.parametrize(
    "args",
    [
        (True, 1, 1),
        (1.0, 1, 1),
        (-1, 1, 1),
        (2**64, 1, 1),
        (1, 0, 1),
        (1, 1, 0),
        (1, True, 1),
        (1, 1, False),
        (1, 2**32, 1),
        (1, 1, 2**32),
    ],
)
def test_invalid_conversion(args):
    reject("validation_error", lambda: api().ticks_to_ns(*args))


def test_conversion_overflow():
    reject("clock_unavailable", lambda: api().ticks_to_ns(2**63, 1, 1))


class Function:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


def fake_clock(monkeypatch, readings, numer=125, denom=3, status=0):
    calls = []
    values = iter(readings)

    def timebase(pointer):
        calls.append("timebase")
        pointer._obj.numer, pointer._obj.denom = numer, denom
        return status

    class Library:
        mach_timebase_info = Function(timebase)
        mach_continuous_time = Function(lambda: next(values))

    library = Library()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: (calls.append("load"), library)[1])
    return calls, library


def test_lazy_ffi_and_signatures(monkeypatch):
    calls, lib = fake_clock(monkeypatch, [3, 3, 6])
    clock = api().DarwinClock()
    assert calls == []
    assert [clock.now_ns(), clock.now_ns(), clock.now_ns()] == [125, 125, 250]
    assert calls == ["load", "timebase"]
    assert lib.mach_continuous_time.restype is ctypes.c_uint64
    assert lib.mach_continuous_time.argtypes == []
    assert lib.mach_timebase_info.restype is ctypes.c_int
    assert len(lib.mach_timebase_info.argtypes) == 1


@pytest.mark.parametrize("kwargs", [{"denom": 0}, {"numer": 0}, {"status": 1}])
def test_bad_timebase(monkeypatch, kwargs):
    fake_clock(monkeypatch, [3], **kwargs)
    reject("clock_unavailable", api().DarwinClock().now_ns)


def test_clock_backwards_sticky(monkeypatch):
    fake_clock(monkeypatch, [10, 9, 100], numer=1, denom=1)
    clock = api().DarwinClock()
    assert clock.now_ns() == 10
    reject("clock_unavailable", clock.now_ns)
    reject("clock_unavailable", clock.now_ns)


def test_clock_missing_symbols_and_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: object())
    reject("clock_unavailable", api().DarwinClock().now_ns)
    monkeypatch.setattr(sys, "platform", "win32")
    reject("platform_unavailable", api().DarwinClock().now_ns)


def test_native_clock(native):
    clock = api().DarwinClock()
    first = clock.now_ns()
    assert type(first) is int and 0 <= first <= clock.now_ns() <= 2**63 - 1


def test_concurrent_clock_serialization(monkeypatch):
    fake_clock(monkeypatch, range(1, 101), numer=1, denom=1)
    clock = api().DarwinClock()
    values, errors = [], []

    def call():
        try:
            values.append(clock.now_ns())
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=call) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert not errors and sorted(values) == list(range(1, 101))


def test_owner_slot_order_and_stale(native, root):
    owner = api().acquire_owner(root)
    try:
        reject("runtime_busy", lambda: api().acquire_owner(root))
        slot = owner.reserve_slot()
        assert not os.get_inheritable(slot.fileno())
        reject("runtime_busy", owner.reserve_slot)
        reject("runtime_busy", owner.close)
        assert owner.release_slot(slot) is True
        reject("invalid_handle", slot.fileno)
        reject("invalid_handle", lambda: owner.release_slot(slot))
        slot2 = owner.reserve_slot()
        assert slot2 is not slot
        assert owner.release_slot(slot2) is True
    finally:
        owner.abandon()
    owner.close()
    reject("invalid_handle", owner.reserve_slot)


@pytest.mark.parametrize("mode", [0o755, 0o770])
def test_unsafe_root_mode(native, root, mode):
    root.chmod(mode)
    reject("runtime_unavailable", lambda: api().acquire_owner(root))


def test_invalid_root_types_and_parent_traversal(root):
    for p in [str(root), Path("relative"), root / ".." / root.name]:
        reject("validation_error", lambda: api().acquire_owner(p))


@pytest.mark.parametrize("kind", ["symlink", "directory", "hardlink", "content", "mode"])
def test_unsafe_lock_file(native, root, kind):
    lock = root / "runtime.owner"
    if kind == "symlink":
        target = root / "other"
        target.touch(mode=0o600)
        lock.symlink_to(target)
    elif kind == "directory":
        lock.mkdir()
    else:
        lock.touch(mode=0o600)
        if kind == "hardlink":
            os.link(lock, root / "other")
        elif kind == "content":
            lock.write_bytes(b"private-sentinel")
        else:
            lock.chmod(0o644)
    reject("runtime_unavailable", lambda: api().acquire_owner(root))
    if kind == "content":
        assert lock.read_bytes() == b"private-sentinel"


def test_parent_and_final_symlink(native, root):
    link = root.parent / "link"
    link.symlink_to(root, target_is_directory=True)
    reject("runtime_unavailable", lambda: api().acquire_owner(link))
    nested = root / "nested"
    nested.mkdir(mode=0o700)
    reject("runtime_unavailable", lambda: api().acquire_owner(link / "nested"))


def test_replacement_and_explicit_abandon(native, root):
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    moved = root.with_name("moved")
    root.rename(moved)
    root.mkdir(mode=0o700)
    try:
        reject("runtime_unavailable", lambda: owner.release_slot(slot))
        owner.abandon()
        owner.abandon()
        assert not list(root.iterdir())
        reject("invalid_handle", slot.fileno)
    finally:
        owner.abandon()


def test_forged_foreign_and_uncopyable(native, root):
    owner = api().acquire_owner(root)
    other_root = root / "second"
    other_root.mkdir(mode=0o700)
    other = api().acquire_owner(other_root)
    try:
        slot = owner.reserve_slot()
        alien = other.reserve_slot()
        reject("invalid_handle", lambda: owner.release_slot(alien))
        forged = object.__new__(api().SlotLease)
        reject("invalid_handle", lambda: owner.release_slot(forged))
        reject("invalid_handle", forged.fileno)
        for obj in (owner, slot, api().DarwinClock()):
            for call in (copy.copy, copy.deepcopy, pickle.dumps):
                with pytest.raises(TypeError):
                    call(obj)
            assert "private-sentinel" not in repr(obj)
        assert owner.release_slot(slot) is True
    finally:
        owner.abandon()
        other.abandon()


def test_inherited_slot_survives_parent_release(native, root, monkeypatch):
    import fcntl

    real_flock = fcntl.flock

    def flock(fd, flags):
        assert not flags & fcntl.LOCK_UN
        return real_flock(fd, flags)

    monkeypatch.setattr(fcntl, "flock", flock)
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    ready_r, ready_w = os.pipe()
    child = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            "import os,sys;os.write(int(sys.argv[1]),b'R');"
            "os.close(int(sys.argv[1]));sys.stdin.buffer.read()",
            str(ready_w),
        ],
        env={},
        pass_fds=(slot.fileno(), ready_w),
        close_fds=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.close(ready_w)
    next_owner = None
    try:
        assert select.select([ready_r], [], [], 3)[0]
        assert os.read(ready_r, 1) == b"R"
        assert owner.release_slot(slot) is False
        owner.close()
        next_owner = api().acquire_owner(root)
        reject("runtime_busy", next_owner.reserve_slot)
        child.stdin.close()
        assert child.wait(timeout=3) == 0
        fresh = next_owner.reserve_slot()
        assert next_owner.release_slot(fresh) is True
    finally:
        child.stdin.close()
        child.wait(timeout=3)
        os.close(ready_r)
        owner.abandon()
        if next_owner:
            next_owner.abandon()


def test_inode_preserved_and_no_fd_growth(native, root):
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    inodes = [(root / name).stat().st_ino for name in ("runtime.owner", "analysis.slot")]
    assert owner.release_slot(slot)
    owner.close()
    # macOS exposes the process's descriptor directory without document content.
    before = len(list(Path("/dev/fd").iterdir()))
    for _ in range(40):
        owner = api().acquire_owner(root)
        try:
            reject("runtime_busy", lambda: api().acquire_owner(root))
            slot = owner.reserve_slot()
            assert owner.release_slot(slot)
        finally:
            owner.abandon()
    assert len(list(Path("/dev/fd").iterdir())) == before
    assert [(root / name).stat().st_ino for name in ("runtime.owner", "analysis.slot")] == inodes


def test_inert_fresh_import_and_constructor():
    script = """
import ctypes, os, socket, subprocess, sys, threading, time
sys.path.insert(0, sys.argv[1])
def forbidden(*a, **k):
    raise AssertionError('unexpected explicit IO')
ctypes.CDLL = forbidden
os.open = os.getenv = os.getpid = forbidden
socket.socket = subprocess.Popen = threading.Thread.start = forbidden
time.time = time.monotonic = time.perf_counter = forbidden
from ara.docx_analysis_worker.macos import DarwinClock, ticks_to_ns
DarwinClock()
assert ticks_to_ns(3,125,3)==125
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve().parents[2] / "src")],
        capture_output=True,
        timeout=5,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")


def test_fork_does_not_adopt_live_handles(native, root):
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    clock = api().DarwinClock()
    clock.now_ns()
    pid = os.fork()
    if pid == 0:
        try:
            for call in (owner.reserve_slot, slot.fileno, clock.now_ns, owner.abandon):
                try:
                    call()
                except api().MacRuntimeError as error:
                    if error.code != "invalid_handle":
                        os._exit(2)
                else:
                    os._exit(3)
            os._exit(0)
        except BaseException:
            os._exit(4)
    try:
        assert os.waitpid(pid, 0) == (pid, 0)
        assert owner.release_slot(slot)
    finally:
        owner.abandon()
