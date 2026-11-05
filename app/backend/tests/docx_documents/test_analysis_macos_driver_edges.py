"""D3: bounded control, parent/guardian death and blocked request transport."""

import importlib
import os
import select
import subprocess
import sys
import threading
import time
import weakref
from pathlib import Path

import pytest

from tests.acceptance.test_docx_analysis_macos_driver import (
    cleanup,
    control,
    native,
    root,
    start,
    wait_for,
)
from tests.acceptance.test_docx_analysis_macos_primitives import api, reject

__all__ = ["native", "root"]


def test_control_caps_short_write_and_backward_clock(monkeypatch):
    port, clock, reader, close = control()
    try:
        os.read(reader, 4096)
        for _ in range(511):
            assert port.renew(600)
            os.read(reader, 4096)
        reject("runtime_unavailable", lambda: port.renew(600))
        assert port.stop_requested and port.error_code == "transport"
    finally:
        close()
        os.close(reader)
    port, clock, reader, close = control()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "write", lambda fd, raw: len(raw) - 1)
            reject("runtime_unavailable", lambda: port.renew(600))
        assert port.error_code == "transport"
    finally:
        close()
        os.close(reader)
    port, clock, reader, close = control()
    try:
        clock.value = 99
        assert not port.check() and port.error_code == "clock"
    finally:
        close()
        os.close(reader)


def test_guardian_death_does_not_claim_orphan_cleanup(native, root, monkeypatch):
    impl = importlib.import_module("ara.docx_analysis_worker.macos._launch")
    original, captured = impl.launch_fixture_guardian, []

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(impl, "launch_fixture_guardian", capture)
    owner, slot, attempt = start(root, "ignore_term")
    try:
        wait_for(attempt, lambda v: v.stage == "analyzing")
        captured[0].process.kill()  # Only this test's retained direct guardian child.
        view = wait_for(attempt, lambda v: v.phase == "blocked")
        assert not view.cleanup_confirmed and not view.candidate_ready
        assert attempt.candidate() is None and attempt.close(timeout=8)
        released = owner.release_slot(slot)
        if not released:
            # The bounded native fixture ends naturally even with its GIL held.
            end = time.monotonic() + 8
            while time.monotonic() < end:
                try:
                    fresh = owner.reserve_slot()
                except api().MacRuntimeError as error:
                    assert error.code == "runtime_busy"
                    time.sleep(0.02)
                else:
                    assert owner.release_slot(fresh)
                    break
            else:
                pytest.fail("bounded orphan fixture retained slot")
    finally:
        attempt.close(timeout=8)
        owner.abandon()


def test_stop_when_request_reader_is_blocked(native, root, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "src"
    child_entry, guardian_entry = root.parent / "child.py", root.parent / "guardian.py"
    child_entry.write_text(
        "import sys,time,os\nfrom pathlib import Path\n"
        + "sys.path.insert(0,"
        + repr(str(source))
        + ")\n"
        + "from ara.docx_analysis_worker.macos import _child_bootstrap as m\n"
        + "original=os.read\n"
        + "def read(fd,n):\n    if fd==0:time.sleep(5)\n    return original(fd,n)\n"
        + "m.os.read=read\nsys.exit(m.main(sys.argv[1:]))\n"
    )
    guardian_entry.write_text(
        "import sys\nfrom pathlib import Path\nsys.path.insert(0,"
        + repr(str(source))
        + ")\n"
        + "from ara.docx_analysis_worker.macos import _guardian as g\n"
        + "g.CHILD_ENTRY=Path("
        + repr(str(child_entry))
        + ")\nsys.exit(g.main(sys.argv[1:]))\n"
    )
    monkeypatch.setattr(
        importlib.import_module("ara.docx_analysis_worker.macos._launch"), "ENTRY", guardian_entry
    )
    owner, slot, attempt = start(root, "wait", request=b"x" * (8 * 1024 * 1024))
    try:
        wait_for(attempt, lambda v: v.phase == "running")
        # The child cannot have consumed the request; Stop does not take its IO lock.
        attempt.stop()
        view = wait_for(attempt, lambda v: v.phase in ("closed", "blocked"))
        assert view.stop_requested and attempt.candidate() is None
    finally:
        cleanup(owner, slot, attempt)


def test_abrupt_supervisor_death_releases_owner_and_eventually_slot(native, root):
    entry = root.parent / "supervisor.py"
    source = Path(__file__).resolve().parents[2] / "src"
    entry.write_text(
        "import sys,os,time\nfrom pathlib import Path\nfrom uuid import UUID\n"
        + "sys.path.insert(0,"
        + repr(str(source))
        + ")\n"
        + "from ara.docx_analysis_worker.macos import acquire_owner,DarwinClock\n"
        + "from ara.docx_analysis_worker.macos.driver import start_fixture_attempt\n"
        + "from ara.docx_analysis_worker.control import AttemptIdentity,make_budget\n"
        + "owner=acquire_owner(Path(sys.argv[1]));slot=owner.reserve_slot()\n"
        + "now=DarwinClock().now_ns()\n"
        + "budget=make_budget(started_ns=now,received_ns=now,"
        + "remaining_deadline_ns=6000000000,remaining_lease_ns=3000000000)\n"
        + "a=start_fixture_attempt(slot,AttemptIdentity(UUID(int=1),UUID(int=2),UUID(int=3),1),"
        + "budget,request=b'fixture',execution_spec=b'spec',mode='ignore_term')\n"
        + "end=time.monotonic()+5\nwhile a.view().stage!='analyzing':\n"
        + "    if time.monotonic()>=end:os._exit(77)\n    time.sleep(.01)\n"
        + "os.write(int(sys.argv[2]),b'R');sys.stdin.buffer.read();os._exit(0)\n"
    )
    reader, writer = os.pipe()
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", str(entry), str(root), str(writer)],
        env={},
        pass_fds=(writer,),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.close(writer)
    owner = None
    try:
        assert select.select([reader], [], [], 5)[0] and os.read(reader, 1) == b"R"
        reject("runtime_busy", lambda: api().acquire_owner(root))
        child.stdin.close()
        assert child.wait(timeout=5) == 0
        owner = api().acquire_owner(root)
        end = time.monotonic() + 8
        while time.monotonic() < end:
            try:
                fresh = owner.reserve_slot()
            except api().MacRuntimeError as error:
                assert error.code == "runtime_busy"
                time.sleep(0.02)
            else:
                assert owner.release_slot(fresh)
                break
        else:
            pytest.fail("guardian did not clean owned fixture after supervisor EOF")
    finally:
        child.stdin.close()
        child.wait(timeout=8)
        os.close(reader)
        if owner is not None:
            owner.abandon()


def test_valid_status_without_normal_guardian_exit_never_candidate(native, root, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "src"
    entry = root.parent / "bad_exit.py"
    entry.write_text(
        "import sys\nsys.path.insert(0,"
        + repr(str(source))
        + ")\n"
        + "from ara.docx_analysis_worker.macos._guardian import main\n"
        + "result=main(sys.argv[1:]);sys.exit(77 if result==0 else result)\n"
    )
    monkeypatch.setattr(
        importlib.import_module("ara.docx_analysis_worker.macos._launch"), "ENTRY", entry
    )
    owner, slot, attempt = start(root)
    try:
        view = wait_for(attempt, lambda v: v.phase == "blocked")
        assert not view.cleanup_confirmed and attempt.candidate() is None
    finally:
        cleanup(owner, slot, attempt)


def test_native_stdout_flood_is_bounded_and_stopped(native, root, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "src"
    child, guardian = root.parent / "flood_child.py", root.parent / "flood_guardian.py"
    child.write_text(
        "import sys,os,time\nsys.path.insert(0,"
        + repr(str(source))
        + ")\n"
        + "from ara.docx_analysis_worker.macos import _fixture_child as fixture\n"
        + "from ara.docx_analysis_worker.macos._child_bootstrap import main\n"
        + "def flood(*a):\n    end=time.monotonic()+5\n"
        + "    while time.monotonic()<end:os.write(1,b'X'*65536)\n    return 76\n"
        + "fixture.run_fixture=flood\nsys.exit(main(sys.argv[1:]))\n"
    )
    guardian.write_text(
        "import sys\nfrom pathlib import Path\nsys.path.insert(0,"
        + repr(str(source))
        + ")\nfrom ara.docx_analysis_worker.macos import _guardian as g\n"
        + "g.CHILD_ENTRY=Path("
        + repr(str(child))
        + ")\nsys.exit(g.main(sys.argv[1:]))\n"
    )
    monkeypatch.setattr(
        importlib.import_module("ara.docx_analysis_worker.macos._launch"), "ENTRY", guardian
    )
    owner, slot, attempt = start(root)
    try:
        view = wait_for(attempt, lambda v: v.phase in ("closed", "blocked"))
        assert view.error_code == "protocol" and attempt.candidate() is None
    finally:
        cleanup(owner, slot, attempt)


def test_driver_import_is_inert():
    source = Path(__file__).resolve().parents[2] / "src"
    script = """
import ctypes,os,sys,threading,subprocess,socket,time
sys.path.insert(0,sys.argv[1])
def forbidden(*a,**k):raise AssertionError('unexpected IO')
os.open=os.getenv=os.getpid=forbidden
ctypes.CDLL=subprocess.Popen=socket.socket=threading.Thread.start=forbidden
time.time=time.monotonic=forbidden
import ara.docx_analysis_worker.macos.driver
"""
    done = subprocess.run(
        [sys.executable, "-c", script, str(source)], capture_output=True, timeout=5
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")


def test_finished_attempt_releases_protocol_buffers(native, root, monkeypatch):
    impl = importlib.import_module("ara.docx_analysis_worker.macos._data_pump")
    original, refs = impl.StreamDecoder, []

    def decoder(*args, **kwargs):
        value = original(*args, **kwargs)
        refs.append(weakref.ref(value))
        return value

    monkeypatch.setattr(impl, "StreamDecoder", decoder)
    owner, slot, attempt = start(root)
    try:
        wait_for(attempt, lambda v: v.phase == "closed")
        assert attempt.close(timeout=8)
        assert refs and all(ref() is None for ref in refs)
    finally:
        cleanup(owner, slot, attempt)


def test_repeated_close_releases_fds_and_keeps_natural_outcome(native, root):
    before = len(list(Path("/dev/fd").iterdir()))
    for _ in range(5):
        owner, slot, attempt = start(root)
        try:
            wait_for(attempt, lambda v: v.phase == "closed")
            assert attempt.close(timeout=8) and attempt.close(timeout=0)
            assert not attempt.view().stop_requested
        finally:
            cleanup(owner, slot, attempt)
    assert len(list(Path("/dev/fd").iterdir())) == before
    assert not any(t.name == "aira-fixture-data" for t in threading.enumerate())
