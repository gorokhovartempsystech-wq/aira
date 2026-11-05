"""Native-shaped calls and unconfirmed completion/failed setup lifetime."""

import ctypes as c
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ara.docx_analysis_worker.windows import WindowsRuntimeError, _events, _io_abi, _pending, _pipes

spec = importlib.util.spec_from_file_location(
    "windows_io_acceptance_support",
    Path(__file__).parents[1] / "acceptance/test_docx_analysis_windows_io.py",
)
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


@pytest.fixture
def io(monkeypatch):
    fake = support.FakeIO()
    monkeypatch.setattr(_pipes, "_load_io", lambda: fake)
    monkeypatch.setattr(_events, "_load_io", lambda: fake)
    return fake


def test_setup_timeout_retains_then_reaps_orphan(io):
    io.connect_status = 997
    clock = support.Clock()
    io.wait_event = lambda handle, ms: setattr(clock, "value", clock.value + 1_000_000_000) or False
    with pytest.raises(WindowsRuntimeError):
        _pipes.create_pipe_pair(deadline_ns=3_000_000_000, clock=clock)
    assert len(_pending._REGISTRY) == 1
    op = next(iter(_pending._REGISTRY.values()))
    assert op._owner._orphaned and op._buffer is not None
    io.complete(op, b"", error=995)
    assert _pending.reap_pending()
    assert not io.live


def test_unknown_query_does_not_release_pending_memory(io):
    pair = support.pair(io)
    op = pair.reader.begin_read()
    op._overlapped.Internal = 0x103
    io.complete(op, b"", error=6)
    with pytest.raises(WindowsRuntimeError):
        op.poll()
    assert not op._done and op._buffer is not None and op.event_handle()
    op._overlapped.Internal = 0
    io.complete(op, b"", error=995)
    assert op.poll().aborted
    assert pair.close()


def test_submission_exception_retains_until_actual_completion(io):
    pair = support.pair(io)
    original = io.read

    def raises_after_issue(*args):
        original(*args)
        raise OSError("sentinel native return lost")

    io.read = raises_after_issue
    with pytest.raises(WindowsRuntimeError):
        pair.reader.begin_read()
    op = pair.reader._operation
    assert op._uncertain and not op._done
    assert pair.reader.close() is False
    io.complete(op, b"ok")
    with pytest.raises(WindowsRuntimeError):
        op.poll()
    assert pair.close() and not io.live


def test_immediate_terminal_start_error_frees_everything(io):
    pair = support.pair(io)
    io.submission = 5
    with pytest.raises(WindowsRuntimeError):
        pair.reader.begin_read()
    assert not _pending._REGISTRY
    assert pair.close() and not io.live


def test_backwards_setup_clock_and_issued_capabilities(io):
    class Backwards:
        def __init__(self):
            self.readings = iter([100, 99])

        def now_ns(self):
            return next(self.readings)

    with pytest.raises(WindowsRuntimeError):
        _pipes.create_pipe_pair(deadline_ns=1_000_000, clock=Backwards())
    assert not io.calls
    event = _events.create_event()
    fake = object.__new__(_events.NativeEvent)
    fake.__dict__.update(event.__dict__)
    with pytest.raises(WindowsRuntimeError):
        fake.set()
    event.close()


def test_native_binding_arguments_and_pending_status(monkeypatch):
    error = [997]
    monkeypatch.setattr(c, "get_last_error", lambda: error[0], raising=False)
    calls = []

    class Function:
        def __init__(self, name):
            self.name = name

        def __call__(self, *args):
            calls.append((self.name, args))
            if self.name in ("CreateEventW", "CreateNamedPipeW", "CreateFileW"):
                return 123
            if self.name in (
                "ReadFile",
                "WriteFile",
                "ConnectNamedPipe",
                "GetOverlappedResult",
                "CancelIoEx",
            ):
                return 0
            return 1

    class Kernel:
        def __getattr__(self, name):
            fn = Function(name)
            setattr(self, name, fn)
            return fn

    base = SimpleNamespace(kernel=Kernel(), close=lambda value: None)
    monkeypatch.setattr(_io_abi, "Native", lambda: base)
    native = _io_abi.IO()
    event = native.event()
    assert calls[-1] == ("CreateEventW", (None, True, False, None))
    event.close()
    ov, buffer = _io_abi.OVERLAPPED(), c.create_string_buffer(12)
    assert native.read(1, buffer, 12, ov) == 997
    assert calls[-1][0] == "ReadFile" and calls[-1][1][3] is None
    assert native.write(1, buffer, 12, ov) == 997
    assert native.result(1, ov) == (997, 0)
    assert calls[-1][1][-1] is False
    error[0] = 1168
    native.cancel(1, ov)
    error[0] = 5
    with pytest.raises(WindowsRuntimeError):
        native.cancel(1, ov)
    assert base.kernel.ReadFile.restype is _io_abi.BOOL
    assert base.kernel.GetOverlappedResult.argtypes[-1] is _io_abi.BOOL


def test_real_pipe_creation_flags_and_peer_queries(monkeypatch):
    from contextlib import contextmanager

    calls = []

    @contextmanager
    def descriptor(base, sid):
        from ara.docx_analysis_worker.windows._abi import SECURITY_ATTRIBUTES

        yield SECURITY_ATTRIBUTES()

    monkeypatch.setattr(_io_abi, "descriptor", descriptor)

    def server(*args):
        calls.append(args)
        return 11

    def peer(handle, out):
        c.cast(out, c.POINTER(c.c_uint32))[0] = 991
        calls.append(handle)
        return 1

    native = object.__new__(_io_abi.IO)
    native.base = SimpleNamespace(close=lambda value: None)
    native.kernel = SimpleNamespace(
        CreateNamedPipeW=server,
        GetNamedPipeClientProcessId=peer,
        GetNamedPipeServerProcessId=peer,
        GetFileType=lambda h: 3,
    )
    handle = native.server("synthetic", "S-1-5-18")
    assert calls[0][1:7] == (0x40080001, 8, 1, 65536, 65536, 0)
    assert native.peer_processes(11, 12) == (991, 991)
    assert calls[-2:] == [11, 11]
    handle.close()


def test_import_is_inert():
    source = str(Path(__file__).resolve().parents[2] / "src")
    program = f"""
import sys,ctypes,os,threading,subprocess
sys.path.insert(0,{source!r})
def forbidden(*a,**kw):raise AssertionError('unexpected IO')
ctypes.CDLL=forbidden
ctypes.WinDLL=forbidden
os.getenv=forbidden
threading.Thread.start=forbidden
subprocess.Popen=forbidden
from ara.docx_analysis_worker.windows import _events,_pending,_pipes,_io_abi
"""
    assert (
        subprocess.run(
            [sys.executable, "-I", "-B", "-c", program], capture_output=True, timeout=5
        ).returncode
        == 0
    )


@pytest.mark.skipif(
    sys.platform != "win32", reason="native Windows stress/backpressure gate pending"
)
def test_native_pending_write_stop_and_repeated_pairs():
    from ara.docx_analysis_worker.windows import WindowsClock

    clock = WindowsClock()
    native = _io_abi._load_io()
    count_fn = native.kernel.GetProcessHandleCount
    count_fn.argtypes = [c.c_void_p, c.POINTER(c.c_uint32)]
    count_fn.restype = c.c_int32
    before, after = c.c_uint32(), c.c_uint32()
    assert count_fn(native.base.kernel.GetCurrentProcess(), c.byref(before))
    for _ in range(100):
        p = _pipes.create_pipe_pair(deadline_ns=clock.now_ns() + 2_000_000_000, clock=clock)
        writer = p.writer.begin_write(b"x" * 65536)
        end = clock.now_ns() + 2_000_000_000
        while writer.poll() is None:
            reader = p.reader.begin_read()
            while reader.poll() is None:
                assert clock.now_ns() < end
                native.wait_event(reader.event_handle(), 10)
        stop = _events.create_event()
        pending = p.reader.begin_read()
        stop.set()
        assert stop.is_set()
        pending.cancel()
        while pending.poll() is None:
            assert clock.now_ns() < end
            native.wait_event(pending.event_handle(), 10)
        assert p.close()
        stop.close()
    assert count_fn(native.base.kernel.GetCurrentProcess(), c.byref(after))
    assert after.value == before.value


def test_duplicate_for_explicit_inheritance_uses_new_handle():
    calls = []
    native = object.__new__(_io_abi.IO)
    native.base = SimpleNamespace(
        duplicate=lambda value, inherit: calls.append((value, inherit)) or 77
    )
    assert native.duplicate(66, True) == 77
    assert calls == [(66, True)]


@pytest.mark.skipif(sys.platform != "win32", reason="native synchronous diagnostics gate pending")
def test_native_synchronous_diagnostic_writer():
    from ara.docx_analysis_worker.windows import WindowsClock

    clock = WindowsClock()
    native = _io_abi._load_io()
    p = _pipes.create_pipe_pair(
        deadline_ns=clock.now_ns() + 2_000_000_000, clock=clock, synchronous_writer=True
    )
    read = p.reader.begin_read()
    count = c.c_uint32()
    data = c.create_string_buffer(b"synthetic diagnostic")
    assert native.kernel.WriteFile(p.writer.handle(), data, len(data) - 1, c.byref(count), None)
    end = clock.now_ns() + 2_000_000_000
    result = read.poll()
    while result is None:
        assert clock.now_ns() < end
        native.wait_event(read.event_handle(), 10)
        result = read.poll()
    assert result.data == b"synthetic diagnostic"
    assert p.close()
