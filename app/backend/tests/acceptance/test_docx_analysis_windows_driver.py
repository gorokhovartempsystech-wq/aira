"""Frozen E4 acceptance: real actor threads, strict synthetic native owners."""

import base64
import hashlib
import importlib
import runpy
import threading
import time
from collections import deque
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import UUID

import pytest

from ara.docx_analysis_worker.control import AttemptIdentity, Budget
from ara.docx_analysis_worker.windows._errors import WindowsRuntimeError
from ara.docx_analysis_worker.windows._launch import Channels, LaunchObservation
from ara.docx_analysis_worker.windows._pending import IOResult
from ara.docx_analysis_worker.wire import StreamDecoder, encode_message

SPEC = b"synthetic-spec"
REPLY = b"fixture-response"


def until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        threading.Event().wait(0.002)
    assert predicate(), "bounded synthetic actor barrier not reached"


class Clock:
    def __init__(self):
        self.value = 1_000_000_000
        self.fail = False

    def now_ns(self):
        if self.fail:
            raise OSError("private diagnostic must not escape")
        return self.value


class Operation:
    def __init__(self, endpoint, data=None):
        self.endpoint, self.data = endpoint, data
        self.cancelled = self.done = False

    def poll(self):
        e = self.endpoint
        e.check()
        if self.done:
            raise AssertionError("terminal operation polled twice")
        if self.cancelled:
            if not e.cancel_ready.is_set():
                return None
            result = IOResult(e.kind, 0, b"", aborted=True)
        elif not e.ready.is_set() or not e.gate():
            return None
        elif self.data is None:
            if not e.chunks:
                return None
            chunk = e.chunks.popleft()
            result = IOResult("read", len(chunk), chunk, eof=not chunk)
        else:
            if e.error:
                raise OSError("private write failure")
            count = len(self.data) if e.short is None else min(e.short, len(self.data))
            e.written.extend(self.data[:count])
            result = IOResult("write", count, b"")
        self.done, e.pending = True, None
        return result

    def cancel(self):
        self.cancelled = True


class Endpoint:
    def __init__(self, kind, chunks=(), gate=lambda: True):
        self.kind, self.chunks, self.gate = kind, deque(chunks), gate
        self.owner, self.pending, self.closed = None, None, False
        self.ready, self.cancel_ready = threading.Event(), threading.Event()
        self.ready.set()
        self.cancel_ready.set()
        self.written = bytearray()
        self.short, self.error = None, False
        self.close_calls = 0

    def check(self):
        current = threading.get_ident()
        if self.owner is None:
            self.owner = current
        assert self.owner == current, "foreign IO owner"

    def begin_read(self):
        return self.begin(None)

    def begin_write(self, data):
        assert type(data) is bytes and 0 < len(data) <= 65536
        return self.begin(data)

    def begin(self, data):
        self.check()
        assert not self.closed and self.pending is None
        self.pending = Operation(self, data)
        return self.pending

    def close(self):
        self.check()
        if self.closed:
            return True
        if self.pending is not None:
            self.pending.cancel()
            if self.pending.poll() is None:
                return False
        self.closed = True
        self.close_calls += 1
        return True


class Holder:
    def __init__(self, binding):
        self.binding, self.owner = binding, None
        self.start_enter, self.start_ready = threading.Event(), threading.Event()
        self.start_ready.set()
        self.stopped = self.hard = self.started = self.closed = False
        self.creation, self.code, self.empty = "created", 0, True
        self.allow_exit = threading.Event()
        self.allow_exit.set()
        self.signals = []
        self.control, self.request = Endpoint("write"), Endpoint("write")
        self.armed = Endpoint("read", [b"AIRA-N1A", b""])
        self.events = Endpoint("read", gate=lambda: self.request.closed)
        self.status = Endpoint("read", gate=lambda: self.request.closed or self.stopped)
        self.fill()

    def fill(self, *, tail=b"", error=False, kind="clean", code=0, cleanup=True):
        digest = hashlib.sha256(SPEC).hexdigest()
        event_values = [
            ("ready", {"execution_spec_sha256": digest}),
            ("stage", {"stage": "loading_model"}),
            ("stage", {"stage": "analyzing"}),
            ("error", {"code": "adapter_error"})
            if error
            else (
                "result",
                {
                    "reply_sha256": hashlib.sha256(REPLY).hexdigest(),
                    "reply_b64": base64.b64encode(REPLY).decode(),
                },
            ),
        ]
        data = b"".join(
            encode_message(self.binding, kind=k, seq=i, values=v)
            for i, (k, v) in enumerate(event_values)
        )
        self.events.chunks = deque([data + tail, b""])
        status = encode_message(
            self.binding,
            kind="closed",
            seq=0,
            values={"exit_kind": kind, "exit_code": code, "cleanup_confirmed": cleanup},
        )
        self.status.chunks = deque([status, b""])

    def check(self):
        if self.owner is None:
            self.owner = threading.get_ident()
        assert self.owner == threading.get_ident(), "foreign process owner"

    def start(self):
        self.check()
        self.start_enter.set()
        assert self.start_ready.wait(4)
        self.started = True
        if self.creation != "created":
            raise WindowsRuntimeError()

    @property
    def channels(self):
        assert self.started
        return Channels(self.control, self.request, self.events, self.status, self.armed)

    def request_stop(self, *, hard=False):
        self.signals.append(hard)
        self.stopped, self.hard = True, self.hard or hard

    def poll_process(self):
        self.check()
        exited = self.started and self.allow_exit.is_set() and (self.request.closed or self.stopped)
        return LaunchObservation(
            self.creation if self.started else "not_started",
            exited,
            self.code if exited else None,
            self.empty if exited else False,
            self.closed,
            False,
        )

    def finish_close(self):
        self.check()
        if self.creation == "unknown":
            return False
        if self.started and self.creation == "created":
            if not self.poll_process().process_exited or not self.empty:
                return False
            assert all(e.closed for e in self.endpoints)
        self.closed = True
        return True

    @property
    def endpoints(self):
        return (self.control, self.request, self.events, self.status, self.armed)


@pytest.fixture
def runtime(monkeypatch):
    driver = importlib.import_module("ara.docx_analysis_worker.windows.driver")
    helpers = runpy.run_path(
        str(Path(__file__).with_name("test_docx_analysis_windows_primitives.py"))
    )
    paths = importlib.import_module("ara.docx_analysis_worker.windows._paths")
    locks = importlib.import_module("ara.docx_analysis_worker.windows._locks")
    monkeypatch.setattr(paths, "_load_filesystem", lambda: helpers["FakeFS"]())
    monkeypatch.setattr(locks.sys, "platform", "win32")
    owner = locks.acquire_owner(r"C:\synthetic")
    slot, clock, holders, attempts = owner.reserve_slot(), Clock(), [], []
    monkeypatch.setattr(driver, "WindowsClock", lambda: clock)

    def prepare(lease, binding, **kwargs):
        assert lease is slot
        holder = Holder(binding)
        holders.append(holder)
        return holder

    monkeypatch.setattr(driver, "prepare_fixture_guardian", prepare)

    def start(configure=lambda h: None, **kwargs):
        original = driver.prepare_fixture_guardian

        def configured(*args, **kw):
            h = original(*args, **kw)
            configure(h)
            return h

        monkeypatch.setattr(driver, "prepare_fixture_guardian", configured)
        try:
            obj = driver.start_fixture_attempt(
                slot,
                AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
                Budget(20_000_000_000, 10_000_000_000, clock.value, 50_000_000),
                request=kwargs.pop("request", b"synthetic-request"),
                execution_spec=kwargs.pop("execution_spec", SPEC),
                **kwargs,
            )
        finally:
            monkeypatch.setattr(driver, "prepare_fixture_guardian", original)
        attempts.append(obj)
        return obj

    yield driver, clock, holders, start
    clock.fail = False
    for h in holders:
        h.start_ready.set()
        h.allow_exit.set()
        h.empty = True
        if h.creation == "unknown":
            h.creation = "failed"  # external proof supplied only by this synthetic harness
        for e in h.endpoints:
            e.cancel_ready.set()
            e.ready.set()
    for obj in attempts:
        obj.stop()
        assert obj.close(3), "actor/native resource retained after synthetic cleanup"
    owner.abandon()


def test_success_uses_three_distinct_owners_and_exact_wire(runtime):
    _, _, holders, start = runtime
    obj = start()
    until(lambda: obj.candidate() is not None)
    h = holders[0]
    assert obj.candidate() == REPLY and obj.candidate() is obj.candidate()
    assert len({h.owner, h.control.owner, h.request.owner}) == 3
    assert h.request.owner == h.events.owner == h.status.owner == h.armed.owner
    assert threading.get_ident() not in {h.owner, h.control.owner, h.request.owner}
    decoder = StreamDecoder(h.binding, lane="request")
    assert decoder.feed(bytes(h.request.written))[0].payload == b"synthetic-request"
    decoder.finish()
    view = obj.view()
    assert view.fixture and view.cleanup_confirmed and view.permit_ready and view.candidate_ready
    with pytest.raises(FrozenInstanceError):
        view.phase = "invented"
    assert "synthetic" not in repr(obj) + repr(view)
    assert obj.close(3) and obj.close(0)
    assert obj.candidate() is None


@pytest.mark.parametrize(
    "missing",
    ["armed_eof", "events_eof", "status_eof", "status", "g_exit", "g_code", "job_empty", "request"],
)
def test_each_missing_proof_rejects_candidate(runtime, missing):
    _, clock, _, start = runtime

    def configure(h):
        if missing == "armed_eof":
            h.armed.chunks.pop()
        elif missing == "events_eof":
            h.events.chunks.pop()
        elif missing == "status_eof":
            h.status.chunks.pop()
        elif missing == "status":
            h.status.chunks.clear()
        elif missing == "g_exit":
            h.allow_exit.clear()
        elif missing == "g_code":
            h.code = 75
        elif missing == "job_empty":
            h.empty = False
        elif missing == "request":
            h.request.ready.clear()

    obj = start(configure)
    until(lambda: obj.view().permit_ready or obj.view().stop_requested)
    assert obj.candidate() is None
    clock.value += 3_000_000_000
    assert obj.candidate() is None
    obj.stop()


@pytest.mark.parametrize(
    "mutation", ["tail", "error", "nonzero", "stopped", "cleanup", "bad_armed", "wrong_spec"]
)
def test_bad_transport_cannot_publish(runtime, mutation):
    _, _, _, start = runtime

    def configure(h):
        if mutation == "tail":
            h.fill(tail=b"x")
        elif mutation == "error":
            h.fill(error=True)
        elif mutation == "nonzero":
            h.fill(kind="crashed", code=7)
        elif mutation == "stopped":
            h.fill(kind="stopped", code=0)
        elif mutation == "cleanup":
            h.fill(cleanup=False)
        elif mutation == "bad_armed":
            h.armed.chunks = deque([b"bad", b""])

    obj = start(configure, execution_spec=b"other" if mutation == "wrong_spec" else SPEC)
    until(lambda: obj.view().stop_requested or obj.view().resources_closed)
    assert obj.candidate() is None


def test_stop_and_close_do_not_wait_for_launch(runtime):
    _, _, holders, start = runtime
    obj = start(lambda h: h.start_ready.clear())
    h = holders[0]
    assert h.start_enter.wait(2)
    obj.stop()
    assert h.stopped and not obj.close(0)
    assert obj.candidate() is None
    for _ in range(100):
        obj.stop()
        assert not obj.renew(11_000_000_000)
    assert len(h.signals) == 1
    h.start_ready.set()


def test_renew_full_receipt_and_busy_control_independent_of_request(runtime):
    _, clock, holders, start = runtime
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    h = holders[0]
    assert obj.renew(12_000_000_000)
    until(lambda: obj._state.command is None)  # owner consumed the accepted receipt
    permits = StreamDecoder(h.binding, lane="control").feed(bytes(h.control.written))
    assert [int(p.values["lease_ns"]) for p in permits] == [10_000_000_000, 12_000_000_000]
    h.control.ready.clear()
    result = []
    caller = threading.Thread(target=lambda: result.append(obj.renew(13_000_000_000)))
    caller.start()
    until(lambda: h.control.pending is not None)
    assert not obj.renew(14_000_000_000)
    assert not result
    clock.value += 51_000_000
    caller.join(2)
    assert result == [False] and obj.view().stop_requested and h.hard


@pytest.mark.parametrize("fault", ["short", "error", "timeout"])
def test_initial_delivery_failure_retains_no_success(runtime, fault):
    _, clock, holders, start = runtime

    def configure(h):
        if fault == "short":
            h.control.short = 1
        elif fault == "error":
            h.control.error = True
        else:
            h.control.ready.clear()

    obj = start(configure)
    until(lambda: holders[0].control.pending is not None or obj.view().stop_requested)
    clock.value += 51_000_000
    until(lambda: obj.view().stop_requested)
    assert not obj.view().permit_ready and obj.candidate() is None and holders[0].hard


def test_cancel_retains_original_worker_and_false_close(runtime):
    _, _, holders, start = runtime
    obj = start(lambda h: (h.request.ready.clear(), h.request.cancel_ready.clear()))
    until(lambda: holders[0].request.pending is not None)
    owner = holders[0].request.owner
    obj.stop()
    assert not obj.close(0.02)
    assert holders[0].request.pending is not None
    assert not holders[0].request.closed
    holders[0].request.cancel_ready.set()
    assert obj.close(3)
    assert holders[0].request.owner == owner


def test_late_stop_and_expiry_revoke_candidate(runtime):
    _, clock, _, start = runtime
    obj = start()
    until(lambda: obj.candidate() is not None)
    clock.value = 10_000_000_000
    assert obj.candidate() is None and obj.view().stop_requested


@pytest.mark.parametrize("value", [True, -1, 2**63, "12", None])
def test_invalid_renew_is_not_admitted(runtime, value):
    _, _, holders, start = runtime
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    before = bytes(holders[0].control.written)
    with pytest.raises(WindowsRuntimeError, match="validation_error"):
        obj.renew(value)
    assert bytes(holders[0].control.written) == before
    assert not obj.view().stop_requested


def test_registry_is_bounded_and_capabilities_not_forgeable(runtime):
    driver, _, _, start = runtime
    with pytest.raises(TypeError):
        driver.WindowsAttempt()
    obj = start(lambda h: h.request.ready.clear())
    with pytest.raises(WindowsRuntimeError, match="runtime_busy"):
        start()
    import copy
    import pickle

    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(obj)


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "wait",
        "native_hang",
        "result_hang",
        "nonzero",
        "tail",
        "error",
        "diagnostic_flood",
        "early_exit",
        "prepared_missing",
        "prepared_extra",
        "exit_259",
        "exit_ntstatus",
    ],
)
@pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="native E4 Windows process/IO gate pending"
)
def test_native_fixture_driver(tmp_path, mode):
    from ara.docx_analysis_worker.windows import WindowsClock, acquire_owner
    from ara.docx_analysis_worker.windows.driver import start_fixture_attempt

    # E1 requires a protected private ACL; reused native preparation helper.
    helpers = runpy.run_path(
        str(Path(__file__).with_name("test_docx_analysis_windows_primitives.py"))
    )
    root = helpers["native_root"].__wrapped__(None, tmp_path)
    owner = acquire_owner(root)
    slot = owner.reserve_slot()
    now = WindowsClock().now_ns()
    obj = start_fixture_attempt(
        slot,
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
        Budget(now + 8_000_000_000, now + 4_000_000_000, now, 0),
        request=b"synthetic",
        execution_spec=SPEC,
        mode=mode,
    )
    try:
        until(
            lambda: (
                obj.candidate() is not None
                or obj.view().stop_requested
                or obj.view().resources_closed
            ),
            12,
        )
        assert (obj.candidate() == REPLY) == (mode == "success")
    finally:
        assert obj.close(15)
        assert owner.release_slot(slot)
        owner.close()
