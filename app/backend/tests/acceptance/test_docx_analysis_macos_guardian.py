"""C1D2 independent token/syscall cases and owned synthetic native processes."""

import base64
import errno
import hashlib
import importlib
import os
import select
import signal
import time
from types import SimpleNamespace
from uuid import UUID

import pytest

from ara.docx_analysis_worker.wire import StreamDecoder, WireBinding, encode_message
from tests.acceptance.test_docx_analysis_macos_primitives import api, native, reject, root

__all__ = ["native", "root"]
BINDING = WireBinding(UUID(int=101), UUID(int=102))
SPEC = b"synthetic-spec"
SPEC_SHA = hashlib.sha256(SPEC).hexdigest()


def module(name):
    return importlib.import_module("ara.docx_analysis_worker.macos." + name)


@pytest.mark.parametrize(
    "kind,token", [("prepared", b"AIRA-N1P"), ("gate", b"AIRA-N1G"), ("armed", b"AIRA-N1A")]
)
def test_tokens_independent_bytes(kind, token):
    reader = module("_bootstrap").TokenReader(kind)
    for byte in token:
        reader.feed(bytes([byte]))
        assert not reader.ready
    reader.finish()
    assert reader.ready


@pytest.mark.parametrize("raw", [b"", b"AIRA", b"AIRA-N1X", b"AIRA-N1P!"])
def test_invalid_token_poisoned(raw):
    reader = module("_bootstrap").TokenReader("prepared")
    reject("runtime_unavailable", lambda: (reader.feed(raw), reader.finish()))
    reject("runtime_unavailable", lambda: reader.feed(b"AIRA-N1P"))


def test_gate_requires_live_writer():
    reader = module("_bootstrap").TokenReader("gate", eof_required=False)
    reader.feed(b"AIRA-N1G")
    assert reader.ready
    reject("runtime_unavailable", reader.finish)


def owned(monkeypatch, *, events=None, waits=None, signal_error=None, registration_error=False):
    impl = module("_ownership")
    calls, pending, results = [], list(events or []), list(waits or [])

    class Child:
        pid, returncode = 321, None

        def poll(self):
            raise AssertionError("Popen poll is forbidden")

        wait = send_signal = terminate = kill = poll

    class Queue:
        def control(self, changes, count, timeout):
            if changes:
                if registration_error:
                    raise OSError("private-sentinel")
                return []
            return pending.pop(0) if pending else []

        def close(self):
            calls.append(("close",))

    def killpg(pid, sig):
        calls.append(("signal", pid, sig))
        if signal_error:
            raise OSError(signal_error, "private-sentinel")

    def waitpid(pid, flags):
        calls.append(("wait", pid, flags))
        item = results.pop(0) if results else (0, 0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(impl, "Popen", Child)
    monkeypatch.setattr(impl.select, "kqueue", Queue)
    monkeypatch.setattr(impl.os, "killpg", killpg)
    monkeypatch.setattr(impl.os, "waitpid", waitpid)
    return impl.OwnedChild(Child()), calls


def exit_event(pid=321):
    return SimpleNamespace(
        ident=pid, filter=select.KQ_FILTER_PROC, flags=0, fflags=select.KQ_NOTE_EXIT
    )


def test_note_exit_before_stop_never_signals(monkeypatch):
    child, calls = owned(monkeypatch, events=[[exit_event()]], waits=[(321, 0)])
    child._poll(1, stop=True)
    assert child.exited and child.exit_code == 0
    child._poll(10, stop=True, force=True)
    assert not any(c[0] == "signal" for c in calls)
    assert calls.count(("wait", 321, os.WNOHANG)) == 1
    child.close()


def test_term_grace_kill_wait_no_further_signals(monkeypatch):
    child, calls = owned(monkeypatch, waits=[(0, 0), (321, signal.SIGKILL)])
    child._poll(10, stop=True)
    child._poll(1_000_000_010, stop=True)
    assert [c[2] for c in calls if c[0] == "signal"] == [signal.SIGTERM]
    child._poll(2_000_000_010, stop=True)
    child._poll(3_000_000_010, force=True)
    assert child.exited and child.exit_code == -signal.SIGKILL
    names = [c[0] for c in calls]
    assert names == ["signal", "signal", "wait", "wait"]
    child.close()


@pytest.mark.parametrize("error", [errno.EPERM, errno.ESRCH, errno.EINTR])
def test_signal_error_is_not_cleanup_and_not_retried(monkeypatch, error):
    child, calls = owned(monkeypatch, waits=[(0, 0), (321, 0)], signal_error=error)
    child._poll(10, stop=True)
    assert child.fault and not child.exited
    child._poll(10_000_000_010, force=True)
    assert child.exited
    assert len([c for c in calls if c[0] == "signal"]) == 1
    child.close()


def test_lost_wait_ownership_does_not_kill_pid(monkeypatch):
    child, calls = owned(monkeypatch, events=[[exit_event()]], waits=[ChildProcessError()])
    child._poll(1)
    assert child.lost and not child.exited
    child._poll(2, force=True)
    assert not any(c[0] == "signal" for c in calls)
    child.close()


def test_registration_failure_never_allows_normal_start(monkeypatch):
    child, calls = owned(monkeypatch, registration_error=True, waits=[(321, 9)])
    assert child.fault
    child._poll(1, force=True)
    assert child.exited and child.exit_code == -9
    assert [c[2] for c in calls if c[0] == "signal"] == [signal.SIGKILL]
    child.close()


def read_to_eof(fd, timeout=5):
    data = bytearray()
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if select.select([fd], [], [], 0.1)[0]:
            chunk = os.read(fd, 65536)
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            assert len(data) <= 100000
    pytest.fail("synthetic pipe EOF timeout")


def exercise(root, mode="success", action=None, permit=True, expired=False):
    clock = api().DarwinClock()
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    start = clock.now_ns()
    deadline, lease = start + 6_000_000_000, start + 1_000_000_000
    if expired:
        lease = start - 1
    launch = module("_launch").launch_fixture_guardian(
        slot, BINDING, deadline_ns=deadline, lease_ns=lease, mode=mode
    )
    try:
        if permit:
            frame = encode_message(
                BINDING,
                kind="permit",
                seq=0,
                values=dict(deadline_ns=str(deadline), lease_ns=str(lease)),
            )
            assert os.write(launch.control_fd, frame) == len(frame)
        armed = read_to_eof(launch.armed_fd)
        if armed == b"AIRA-N1A":
            raw = b"synthetic-request"
            frame = encode_message(
                BINDING,
                kind="run",
                seq=0,
                values=dict(
                    worker_instance_id=str(UUID(int=103)),
                    claim_fence=1,
                    request_b64=base64.b64encode(raw).decode(),
                    request_sha256=hashlib.sha256(raw).hexdigest(),
                    execution_spec_b64=base64.b64encode(SPEC).decode(),
                    execution_spec_sha256=SPEC_SHA,
                ),
            )
            assert os.write(launch.request_fd, frame) == len(frame)
            launch.close_request()
            if action == "stop":
                decoder = StreamDecoder(
                    BINDING, lane="events", expected_execution_spec_sha256=SPEC_SHA
                )
                until = time.monotonic() + 3
                messages = []
                while not any(
                    m.kind == "stage" and m.values["stage"] == "analyzing" for m in messages
                ):
                    assert time.monotonic() < until
                    if select.select([launch.events_fd], [], [], 0.1)[0]:
                        messages.extend(decoder.feed(os.read(launch.events_fd, 65536)))
                launch.close_control()
        events = read_to_eof(launch.events_fd, timeout=8)
        status = read_to_eof(launch.status_fd, timeout=8)
        code = launch.process.wait(timeout=8)
        message = None
        if status:
            decoder = StreamDecoder(BINDING, lane="status")
            (message,) = decoder.feed(status)
            decoder.finish()
        return armed, events, message, code
    finally:
        launch.close()
        launch.process.wait(timeout=10)
        assert owner.release_slot(slot)
        owner.close()


def test_native_fixture_success(native, root):
    armed, events, status, code = exercise(root)
    assert armed == b"AIRA-N1A" and code == 0
    assert dict(status.values) == dict(exit_kind="clean", exit_code=0, cleanup_confirmed=True)
    decoder = StreamDecoder(BINDING, lane="events", expected_execution_spec_sha256=SPEC_SHA)
    messages = decoder.feed(events)
    decoder.finish()
    assert messages[-1].payload == b"fixture-response"


def test_native_stop_independent_of_model_request(native, root):
    _, _, status, code = exercise(root, "wait", "stop")
    assert code == 0 and status.values["cleanup_confirmed"]
    assert status.values["exit_kind"] == "stopped"


def test_native_ignore_term_native_gil_hang_killed(native, root):
    _, _, status, code = exercise(root, "ignore_term", "stop")
    assert code == 0 and status.values["exit_code"] == -9
    assert status.values["exit_kind"] == "stopped"


@pytest.mark.parametrize("mode", ["prepared_missing", "prepared_extra", "early_exit"])
def test_native_bootstrap_fault_no_armed(native, root, mode):
    armed, _, status, _ = exercise(root, mode)
    assert armed == b""
    assert status is None or status.values["exit_kind"] != "clean"


@pytest.mark.parametrize("kwargs", [{"permit": False}, {"expired": True}])
def test_native_no_spawn_before_valid_live_permit(native, root, kwargs):
    armed, events, status, code = exercise(root, **kwargs)
    assert armed == events == b"" and status is None and code != 0


def test_native_stderr_flood_cannot_be_clean(native, root):
    _, _, status, code = exercise(root, "stderr_flood")
    assert code == 0 and status.values["cleanup_confirmed"]
    assert status.values["exit_kind"] == "crashed"


def test_native_result_then_hang_not_clean(native, root):
    _, events, status, code = exercise(root, "result_hang")
    assert b"fixture" not in repr(status).encode()
    assert events and code == 0 and status.values["exit_kind"] != "clean"
