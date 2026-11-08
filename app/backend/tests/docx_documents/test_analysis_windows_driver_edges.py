"""Additional barriers and lifetime tests; frozen E4 acceptance stays independent."""

import gc
import importlib
import runpy
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path

import pytest

from ara.docx_analysis_worker.windows._errors import WindowsRuntimeError

helpers = runpy.run_path(
    str(Path(__file__).parents[1] / "acceptance/test_docx_analysis_windows_driver.py")
)
runtime, until, REPLY = helpers["runtime"], helpers["until"], helpers["REPLY"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request": b""},
        {"request": bytearray(b"x")},
        {"request": b"x" * (8 * 1024 * 1024 + 1)},
        {"execution_spec": b""},
        {"execution_spec": b"x" * 4097},
        {"mode": "arbitrary"},
    ],
)
def test_invalid_factory_does_not_create_holder(runtime, kwargs):
    _, _, holders, start = runtime
    with pytest.raises(WindowsRuntimeError, match="validation_error"):
        start(**kwargs)
    assert not holders


@pytest.mark.parametrize("timeout", [True, -1, 31, float("nan"), float("inf"), "5", None])
def test_close_validation_before_mutation(runtime, timeout):
    _, _, holders, start = runtime
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    with pytest.raises(WindowsRuntimeError, match="validation_error"):
        obj.close(timeout)
    assert not obj.view().stop_requested and not holders[0].stopped


def test_safe_stop_validation_and_process_capability(runtime):
    _, _, _, start = runtime
    obj = start(lambda h: h.request.ready.clear())
    for reason in (True, None, "unknown"):
        with pytest.raises(WindowsRuntimeError, match="validation_error"):
            obj.stop(reason)
    assert not obj.view().stop_requested
    original = obj._pid
    try:
        obj._pid = -1
        for method in (obj.view, obj.candidate, obj.close, obj.stop):
            with pytest.raises(WindowsRuntimeError, match="invalid_handle"):
                method()
    finally:
        obj._pid = original


def test_accepted_receipt_is_not_expired_by_delayed_owner(runtime, monkeypatch):
    _, clock, _, start = runtime
    writer = importlib.import_module("ara.docx_analysis_worker.windows._control_writer")
    original = writer.Writer.send
    held, release = threading.Event(), threading.Event()

    def send(self, lease, cutoff, command=None):
        result = original(self, lease, cutoff, command)
        if command is not None:
            held.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(writer.Writer, "send", send)
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    try:
        assert obj.renew(12_000_000_000)
        assert held.wait(2)
        clock.value += 60_000_000
        assert obj._state.tick() is not None
        assert not obj.view().stop_requested
        assert obj._state.lease == 12_000_000_000
    finally:
        release.set()


def test_provisional_receipt_expires_without_caller_acceptance(runtime, monkeypatch):
    _, clock, holders, start = runtime
    state_module = importlib.import_module("ara.docx_analysis_worker.windows._attempt_state")
    original = state_module.State.tick
    entered, release = threading.Event(), threading.Event()
    calls = []

    def tick(self):
        if threading.current_thread().name == "delayed-renew":
            calls.append(1)
            if len(calls) == 2:
                entered.set()
                assert release.wait(3)
        return original(self)

    monkeypatch.setattr(state_module.State, "tick", tick)
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    results = []
    caller = threading.Thread(
        target=lambda: results.append(obj.renew(12_000_000_000)), name="delayed-renew"
    )
    caller.start()
    try:
        assert entered.wait(2)
        until(lambda: obj._state.command is not None and obj._state.command.receipt)
        clock.value += 51_000_000
        until(lambda: obj.view().stop_requested)
        assert obj._state.lease == 10_000_000_000 and holders[0].hard
    finally:
        release.set()
        caller.join(2)
    assert results == [False]


def test_stop_cancels_pending_receipt_without_new_hard_fault(runtime):
    _, _, holders, start = runtime
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    h = holders[0]
    h.control.ready.clear()
    results = []
    caller = threading.Thread(target=lambda: results.append(obj.renew(12_000_000_000)))
    caller.start()
    until(lambda: h.control.pending is not None)
    obj.stop()
    caller.join(2)
    assert results == [False] and not h.hard
    assert obj._state.lease == 10_000_000_000


@pytest.mark.parametrize("cap", ["frames", "bytes"])
def test_control_caps_checked_before_native_submission(runtime, monkeypatch, cap):
    _, _, holders, start = runtime
    writer = importlib.import_module("ara.docx_analysis_worker.windows._control_writer")
    original = writer.Writer.send

    def send(self, lease, cutoff, command=None):
        if command is not None:
            if cap == "frames":
                self.seq = 512
            else:
                self.total = 1024 * 1024
        return original(self, lease, cutoff, command)

    monkeypatch.setattr(writer.Writer, "send", send)
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    before = bytes(holders[0].control.written)
    assert not obj.renew(12_000_000_000)
    assert holders[0].hard and bytes(holders[0].control.written) == before


def test_large_request_handles_partial_write_without_repeating_prefix(runtime):
    _, _, holders, start = runtime
    request = b"uniquely bounded request " * 10000
    obj = start(lambda h: setattr(h.request, "short", 32768), request=request)
    until(lambda: obj.candidate() is not None)
    decoder = helpers["StreamDecoder"](holders[0].binding, lane="request")
    encoded = bytes(holders[0].request.written)
    messages = []
    for pos in range(0, len(encoded), 65536):
        messages.extend(decoder.feed(encoded[pos : pos + 65536]))
    decoder.finish()
    assert len(messages) == 1 and messages[0].payload == request


def test_tail_deadline_is_not_extended_by_repeated_polls(runtime):
    _, clock, holders, start = runtime
    obj = start(lambda h: h.events.chunks.pop())
    until(lambda: obj._state.status is not None and obj._state.observation.process_exited)
    clock.value += 2_000_000_000
    until(lambda: obj.view().stop_requested)
    assert obj.candidate() is None and holders[0].hard


def test_close_uses_one_deadline_and_retains_each_pending_owner(runtime):
    _, _, holders, start = runtime

    def configure(h):
        h.request.ready.clear()
        for e in h.endpoints:
            e.cancel_ready.clear()

    obj = start(configure)
    until(lambda: holders[0].request.pending is not None)
    before = time.monotonic()
    assert not obj.close(0.03)
    assert time.monotonic() - before < 0.15
    assert not obj.view().resources_closed
    for endpoint in holders[0].endpoints:
        endpoint.cancel_ready.set()
    assert obj.close(3)


def test_registry_retains_dropped_handle_and_close_releases_it(runtime):
    _, _, _, start = runtime
    obj = start()
    until(obj.candidate)
    ref = weakref.ref(obj)
    del obj
    gc.collect()
    assert ref() is not None
    with pytest.raises(WindowsRuntimeError, match="runtime_busy"):
        start()
    assert ref().close(3)
    next_obj = start()
    until(lambda: next_obj.candidate() is not None)


@pytest.mark.parametrize("position", ["launch", "control", "data"])
def test_start_exception_after_thread_entry_never_opens_native_gate(runtime, monkeypatch, position):
    _, _, holders, start = runtime
    original = threading.Thread.start

    def injected(self):
        result = original(self)
        if self.name == "aira-fixture-" + position:
            raise RuntimeError("synthetic after-start uncertainty")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", injected)
        obj = start()
    until(lambda: obj.view().resources_closed)
    assert not holders[0].start_enter.is_set()
    assert obj.candidate() is None and obj.close(3)


def test_clock_failure_revokes_reply_and_has_fixed_error(runtime):
    _, clock, _, start = runtime
    obj = start()
    until(lambda: obj.candidate() is not None)
    clock.fail = True
    assert obj.candidate() is None
    assert obj.view().error_code == "clock"
    assert "private" not in repr(obj.view())
    clock.fail = False


def test_metadata_view_never_reads_clock(runtime):
    _, _, _, start = runtime
    obj = start()
    until(lambda: obj.view().resources_closed)
    until(lambda: all(obj._state.done.values()))

    class Denied:
        def now_ns(self):
            raise AssertionError("view performed IO")

    obj._state.clock = Denied()
    assert obj.view().candidate_ready
    # Restore for the fixture's explicit stop/cleanup, which may use clock.
    obj._state.clock = runtime[1]


def test_cross_thread_sample_publication_uses_watermark(runtime):
    _, clock, _, start = runtime
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    state = obj._state
    clock.value += 100_000_000
    assert state.tick() == clock.value
    clock.value -= 50_000_000  # models delayed publication, not a native clock guarantee
    assert state.tick() == 1_100_000_000
    assert not obj.view().stop_requested


def test_one_hundred_completed_attempts_leave_no_actor_threads(runtime):
    _, _, _, start = runtime
    baseline = {t.ident for t in threading.enumerate() if t.name.startswith("aira-fixture-")}
    for _ in range(100):
        obj = start()
        until(lambda: obj.candidate() is not None)
        assert obj.candidate() == REPLY and obj.close(3)
    assert {
        t.ident for t in threading.enumerate() if t.name.startswith("aira-fixture-")
    } == baseline


def test_driver_import_inert_in_fresh_process():
    source = str(Path(__file__).resolve().parents[2] / "src")
    script = f"""
import sys, os, ctypes, subprocess, threading
sys.path.insert(0, {source!r})
def denied(*args, **kwargs): raise AssertionError('unexpected IO')
ctypes.CDLL = ctypes.WinDLL = denied
subprocess.Popen = threading.Thread.start = os.getenv = denied
import ara.docx_analysis_worker.windows.driver
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script], capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode()


def test_unknown_creation_is_not_cured_by_empty_job_or_close_timeout(runtime):
    _, _, holders, start = runtime
    obj = start(lambda h: setattr(h, "creation", "unknown"))
    until(lambda: obj.view().stop_requested)
    assert not obj.close(0.02)
    assert not obj.view().resources_closed and not obj.view().cleanup_confirmed
    assert obj.candidate() is None
    # The synthetic harness can provide an explicit known failure; real E3 cannot guess it.
    holders[0].creation = "failed"
    assert obj.close(3)


def test_known_failed_create_closes_without_invented_model_status(runtime):
    _, _, _, start = runtime
    obj = start(lambda h: setattr(h, "creation", "failed"))
    until(lambda: obj.view().resources_closed)
    assert obj.close(3)
    assert not obj.view().cleanup_confirmed and obj.view().exit_code is None
    assert obj.candidate() is None


def test_explicit_late_stop_revokes_identical_reply(runtime):
    _, _, holders, start = runtime
    obj = start()
    until(lambda: obj.candidate() is not None)
    assert obj.candidate() is obj.candidate()
    obj.stop()
    assert obj.candidate() is None and not obj.view().candidate_ready
    assert not holders[0].hard


def test_view_closed_resources_alone_never_creates_candidate(runtime):
    _, _, holders, start = runtime

    def configure(h):
        h.status.chunks.clear()

    obj = start(configure)
    until(lambda: holders[0].request.closed)
    obj.stop()
    assert obj.close(3)
    assert obj.view().resources_closed and not obj.view().cleanup_confirmed
    assert obj.candidate() is None


def test_stop_does_not_wait_for_native_control_poll(runtime, monkeypatch):
    _, _, holders, start = runtime
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    operation = helpers["Operation"]
    original = operation.poll
    held, release = threading.Event(), threading.Event()

    def poll(self):
        if self.endpoint is holders[0].control:
            held.set()
            assert release.wait(3)
        return original(self)

    results = []
    with monkeypatch.context() as patch:
        patch.setattr(operation, "poll", poll)
        caller = threading.Thread(target=lambda: results.append(obj.renew(12_000_000_000)))
        caller.start()
        try:
            assert held.wait(2)
            obj.stop()
            assert not obj.close(0)
            caller.join(2)
            assert results == [False] and obj._state.lease == 10_000_000_000
        finally:
            release.set()
    assert obj.close(3) and obj.candidate() is None


def test_natural_completion_finishes_unaccepted_renew_without_extending_lease(runtime, monkeypatch):
    _, _, holders, start = runtime
    writer = importlib.import_module("ara.docx_analysis_worker.windows._control_writer")
    original = writer.Writer.send
    held, release = threading.Event(), threading.Event()

    def send(self, lease, cutoff, command=None):
        if command is not None:
            held.set()
            assert release.wait(3)
        return original(self, lease, cutoff, command)

    monkeypatch.setattr(writer.Writer, "send", send)
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)
    results = []
    caller = threading.Thread(target=lambda: results.append(obj.renew(12_000_000_000)))
    caller.start()
    try:
        assert held.wait(2)
        holders[0].request.ready.set()
        until(lambda: obj.candidate() is not None)
        caller.join(2)
        assert results == [False] and obj._state.lease == 10_000_000_000
    finally:
        release.set()
    until(lambda: obj.view().resources_closed)
    assert not obj.view().stop_requested and obj.candidate() == REPLY


@pytest.mark.skipif(
    sys.platform != "win32", reason="native E4 Windows HANDLE/thread stress pending"
)
def test_native_one_hundred_drivers_no_handle_or_thread_growth(tmp_path):
    import ctypes as c

    api = importlib.import_module("ara.docx_analysis_worker.windows._process_abi").ProcessAPI()
    count = api.kernel.GetProcessHandleCount
    count.argtypes, count.restype = [c.c_void_p, c.POINTER(c.c_uint32)], c.c_int32

    def handles():
        value = c.c_uint32()
        assert count(api.kernel.GetCurrentProcess(), c.byref(value))
        return value.value

    warm = tmp_path / "warm"
    warm.mkdir()
    helpers["test_native_fixture_driver"](warm, "success")
    before_handles, before_threads = handles(), len(threading.enumerate())
    for index in range(100):
        directory = tmp_path / str(index)
        directory.mkdir()
        helpers["test_native_fixture_driver"](directory, "success")
    assert handles() == before_handles and len(threading.enumerate()) == before_threads


@pytest.mark.skipif(
    sys.platform != "win32", reason="native E4 guardian death with known M startup pending"
)
def test_native_guardian_death_rejects_reply_and_drains_owned_job(tmp_path, monkeypatch):
    from uuid import UUID

    from ara.docx_analysis_worker.control import AttemptIdentity, Budget
    from ara.docx_analysis_worker.windows import WindowsClock, acquire_owner
    from ara.docx_analysis_worker.windows.driver import start_fixture_attempt

    launch = importlib.import_module("ara.docx_analysis_worker.windows._launch")
    primitive = runpy.run_path(
        str(Path(__file__).parents[1] / "acceptance/test_docx_analysis_windows_primitives.py")
    )
    root = primitive["native_root"].__wrapped__(None, tmp_path)
    owner = acquire_owner(root)
    slot = owner.reserve_slot()
    wanted, killed = threading.Event(), threading.Event()
    original = launch.FixtureLaunch.poll_process

    def poll(self):
        if wanted.is_set() and not killed.is_set():
            self._check(True)
            self._record.api.terminate_process(self._record._process.value)
            killed.set()
        return original(self)

    monkeypatch.setattr(launch.FixtureLaunch, "poll_process", poll)
    now = WindowsClock().now_ns()
    obj = start_fixture_attempt(
        slot,
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
        Budget(now + 20_000_000_000, now + 15_000_000_000, now, 0),
        request=b"synthetic",
        execution_spec=helpers["SPEC"],
        mode="wait",
    )
    try:
        until(lambda: obj.view().stage == "analyzing", 10)
        wanted.set()
        assert killed.wait(3)
        until(lambda: obj.view().stop_requested, 3)
        assert obj.candidate() is None and not obj.view().cleanup_confirmed
    finally:
        assert obj.close(15)
        assert owner.release_slot(slot)
        owner.close()



def test_closed_control_pipe_during_renewal_leaves_completion_to_data_reader(runtime, monkeypatch):
    _, _, holders, start = runtime
    writer = importlib.import_module("ara.docx_analysis_worker.windows._control_writer")
    from types import SimpleNamespace

    original = writer.Writer.send

    def send(self, lease, cutoff, command=None):
        if command is not None:
            self.endpoint = SimpleNamespace(
                begin_write=lambda frame: SimpleNamespace(
                    poll=lambda: SimpleNamespace(eof=True, aborted=False, count=0)
                )
            )
        return original(self, lease, cutoff, command)

    monkeypatch.setattr(writer.Writer, "send", send)
    obj = start(lambda h: h.request.ready.clear())
    until(lambda: obj.view().permit_ready)

    assert not obj.renew(12_000_000_000)
    assert obj._state.control_eof
    assert obj._state.lease != 12_000_000_000
    assert not obj.view().stop_requested
    assert not obj.view().candidate_ready
    assert not holders[0].stopped
    assert not obj.renew(12_000_000_000)
