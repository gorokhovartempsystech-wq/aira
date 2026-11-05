"""C1E2 frozen bounded IO and completion lifetime acceptance."""

import ctypes as c
import importlib
import os
import threading

import pytest


def module(name):
    return importlib.import_module("ara.docx_analysis_worker.windows." + name)


def reject(call, code="runtime_unavailable"):
    from ara.docx_analysis_worker.windows import WindowsRuntimeError

    with pytest.raises(WindowsRuntimeError) as exc:
        call()
    assert exc.value.code == code


class FakeIO:
    def __init__(self):
        self.next = 100
        self.live, self.ops, self.calls, self.signals = set(), {}, [], set()
        self.connect_status, self.cancel_error, self.submission = 535, 0, 997
        self.peers = None

    def handle(self):
        self.next += 1
        self.live.add(self.next)
        return module("_handles").OwnedHandle(self, self.next)

    def event(self):
        self.calls.append(("event",))
        return self.handle()

    def close(self, value):
        self.calls.append(("close", value))
        self.live.remove(value)

    def set_event(self, value):
        self.signals.add(value)

    def wait_event(self, value, timeout):
        self.calls.append(("wait", timeout))
        return value in self.signals

    def user(self):
        return "S-1-5-21-1-2-3-1001"

    def server(self, name, sid):
        self.calls.append(("server", name, sid))
        return self.handle()

    def client(self, name, synchronous):
        self.calls.append(("client", name, synchronous))
        return self.handle()

    def peer_processes(self, server, client):
        return self.peers or (os.getpid(), os.getpid())

    def pid(self):
        return os.getpid()

    def connect(self, handle, overlapped):
        self.ops[c.addressof(overlapped)] = [None, 0, None]
        return self.connect_status

    def read(self, handle, buffer, size, overlapped):
        self.ops[c.addressof(overlapped)] = [buffer, size, None]
        return self.submission

    def write(self, handle, buffer, size, overlapped):
        self.ops[c.addressof(overlapped)] = [buffer, size, None]
        return self.submission

    def result(self, handle, overlapped):
        _, _, result = self.ops[c.addressof(overlapped)]
        return result or (996, 0)

    def cancel(self, handle, overlapped):
        self.calls.append(("cancel", handle))
        if self.cancel_error not in (0, 1168):
            raise OSError("sentinel cancel")

    def complete(self, op, data=b"abc", error=0, count=None):
        record = self.ops[c.addressof(op._overlapped)]
        if record[0] is not None and data:
            c.memmove(record[0], data, min(len(data), record[1]))
        record[2] = (error, len(data) if count is None else count)


class Clock:
    def __init__(self):
        self.value = 1_000_000_000

    def now_ns(self):
        return self.value


@pytest.fixture
def io(monkeypatch):
    value = FakeIO()
    monkeypatch.setattr(module("_events"), "_load_io", lambda: value)
    monkeypatch.setattr(module("_pipes"), "_load_io", lambda: value)
    return value


def pair(io, synchronous=False):
    return module("_pipes").create_pipe_pair(
        deadline_ns=3_000_000_000, clock=Clock(), synchronous_writer=synchronous
    )


def test_event_lifecycle(io):
    event = module("_events").create_event()
    assert not event.is_set()
    event.set()
    assert event.is_set()
    assert "100" not in repr(event)
    event.close()
    event.close()
    reject(event.handle, "invalid_handle")
    assert not io.live


def test_overlapped_layout():
    cls = module("_io_abi").OVERLAPPED
    assert c.sizeof(cls) == 32
    assert cls.hEvent.offset == 24 and cls.Offset.offset == 16


@pytest.mark.parametrize("size", [0, -1, True, 65537, 1.0])
def test_read_limits_without_submission(io, size):
    p = pair(io)
    count = len(io.ops)
    reject(lambda: p.reader.begin_read(size), "validation_error")
    assert len(io.ops) == count
    assert p.close()


@pytest.mark.parametrize("data", [b"", b"x" * 65537, bytearray(b"x"), "text", None])
def test_write_limits(io, data):
    p = pair(io)
    reject(lambda: p.writer.begin_write(data), "validation_error")
    assert p.close()


def test_partial_result_is_immutable_and_repeatable(io):
    p = pair(io)
    op = p.reader.begin_read(100)
    assert op.poll() is None
    reject(lambda: p.reader.begin_read(1), "runtime_busy")
    io.complete(op)
    result = op.poll()
    assert result.data == b"abc" and result.count == 3 and not result.eof
    assert op.poll() is result
    assert "abc" not in repr(result)
    assert p.close()
    assert not io.live


@pytest.mark.parametrize("error,eof,aborted", [(109, True, False), (995, False, True)])
def test_terminal_eof_and_cancel(io, error, eof, aborted):
    p = pair(io)
    op = p.reader.begin_read()
    io.complete(op, b"", error=error)
    result = op.poll()
    assert result.eof is eof and result.aborted is aborted and result.data == b""
    assert p.close()


@pytest.mark.parametrize("error,count", [(5, 0), (0, 0), (0, 65537)])
def test_terminal_error_and_zero_progress(io, error, count):
    p = pair(io)
    op = p.reader.begin_read()
    io.complete(op, b"", error=error, count=count)
    reject(op.poll)
    reject(op.poll)
    assert p.close()
    assert not io.live


@pytest.mark.parametrize("cancel_error", [0, 1168, 5])
def test_cancel_is_not_completion(io, cancel_error):
    p = pair(io)
    op = p.reader.begin_read()
    before = set(io.live)
    io.cancel_error = cancel_error
    if cancel_error == 5:
        reject(op.cancel)
    else:
        op.cancel()
    assert op.poll() is None and io.live == before
    io.complete(op, b"ok")
    assert op.poll().data == b"ok"
    assert p.close()


def test_close_pending_and_foreign_thread_cancel(io):
    p = pair(io)
    op = p.reader.begin_read()
    errors = []

    def other_thread():
        op.cancel()
        try:
            p.reader.close()
        except Exception as exc:
            errors.append(exc.code)

    worker = threading.Thread(target=other_thread)
    worker.start()
    worker.join()
    assert errors == ["invalid_handle"]
    assert p.reader.close() is False
    io.complete(op, b"", error=995)
    assert p.reader.close() is True
    assert p.close()
    assert not io.live


def test_registry_retains_pending_buffer_and_caps_before_io(io):
    import gc
    import weakref

    pairs, pending = [], []
    for _ in range(64):
        p = pair(io)
        pairs.append(p)
        pending.append(p.reader.begin_read(1))
    ref = weakref.ref(pending[0])
    del pending[0]
    gc.collect()
    assert ref() is not None
    extra = None
    # Connect also reserves capacity, even when it completes immediately.
    before = len(io.ops)
    reject(lambda: pair(io), "runtime_busy")
    assert len(io.ops) == before
    extra = ref()
    for op in [extra, *pending]:
        io.complete(op, b"", error=995)
        assert op.poll().aborted
    for p in pairs:
        assert p.close()
    del extra
    assert not io.live


@pytest.mark.parametrize(
    "kwargs",
    [{"deadline_ns": True}, {"deadline_ns": -1}, {"deadline_ns": 2**63}, {"synchronous_writer": 1}],
)
def test_setup_invalid_without_io(io, kwargs):
    values = {"deadline_ns": 3_000_000_000, "clock": Clock()}
    values.update(kwargs)
    reject(lambda: module("_pipes").create_pipe_pair(**values), "validation_error")
    assert io.calls == []


def test_foreign_peer_and_no_reconnect(io):
    io.peers = (123, 456)
    reject(lambda: pair(io))
    assert not io.live
    names = [call[1] for call in io.calls if call[0] == "server"]
    assert len(names) == 1 and names[0].startswith("\\\\.\\pipe\\aira-")


def test_direction_and_synchronous_writer(io):
    p = pair(io, True)
    reject(lambda: p.reader.begin_write(b"x"), "invalid_handle")
    reject(p.writer.begin_read, "invalid_handle")
    reject(lambda: p.writer.begin_write(b"x"), "invalid_handle")
    assert p.close()


@pytest.mark.skipif(os.name != "nt", reason="native Windows IO gate pending")
def test_native_pair_roundtrip_and_cancel():
    from ara.docx_analysis_worker.windows import WindowsClock

    clock = WindowsClock()
    p = module("_pipes").create_pipe_pair(deadline_ns=clock.now_ns() + 2_000_000_000, clock=clock)
    read = p.reader.begin_read()
    write = p.writer.begin_write(b"synthetic")
    end = clock.now_ns() + 2_000_000_000
    got = sent = None
    while got is None or sent is None:
        got = got or read.poll()
        sent = sent or write.poll()
        assert clock.now_ns() < end
        if got is None:
            module("_io_abi")._load_io().wait_event(read.event_handle(), 10)
    assert got.data == b"synthetic" and sent.count == 9
    read = p.reader.begin_read()
    read.cancel()
    while read.poll() is None:
        assert clock.now_ns() < end
    assert p.close()
