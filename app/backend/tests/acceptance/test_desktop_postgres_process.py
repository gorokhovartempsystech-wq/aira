"""Independent command ownership, bounded output and lifetime acceptance."""

import copy
import dataclasses
import gc
import importlib
import os
import pickle
import subprocess
import sys
import time
import weakref
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS command ownership")


def api():
    return importlib.import_module("ara.desktop.postgres_process")


def reject(code, call):
    with pytest.raises(api().CommandError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in repr(caught.value) + str(caught.value)


def until(predicate, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    pytest.fail("Synthetic command did not reach the expected state")


def done(command):
    until(lambda: not command.view().resources_pending)
    return command.view()


def command(owner, root, program="print('synthetic result')", **kwargs):
    return api().OwnedCommand(
        owner, Path(sys.executable), ("-I", "-c", program), cwd=root, **kwargs
    )


@pytest.fixture
def owned(tmp_path):
    from ara.docx_analysis_worker.macos import acquire_owner

    root = tmp_path.resolve() / "SYNTHETIC_PRIVATE"
    root.mkdir(mode=0o700)
    owner = acquire_owner(root)
    yield owner, root
    owner.close()


def test_constructor_inert_and_capture_is_exact(owned):
    owner, root = owned
    job = command(owner, root, capture_stdout=True)
    assert job.view().phase == "new" and not job.view().resources_pending
    assert not (root / "analysis.slot").exists()
    assert "SYNTHETIC_PRIVATE" not in repr(job) + repr(job.view())
    reject("invalid_handle", job.stdout)
    job.start()
    view = done(job)
    assert view.phase == "exited" and view.returncode == 0 and view.error_code is None
    assert job.stdout() == b"synthetic result\n"
    assert job.shutdown() and job.shutdown(0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.phase = "running"
    slot = owner.reserve_slot()
    assert owner.release_slot(slot)


def test_new_shutdown_does_not_close_borrowed_owner(owned):
    owner, root = owned
    job = command(owner, root)
    assert job.shutdown()
    assert job.view().phase == "exited" and not job.view().resources_pending
    reject("invalid_handle", job.start)
    slot = owner.reserve_slot()
    assert owner.release_slot(slot)


def test_nonzero_and_output_limit_are_not_success(owned):
    owner, root = owned
    for program, error in (
        ("raise SystemExit(23)", "process_failed"),
        ("import os; os.write(1,b'x'*100000)", "output_limit"),
    ):
        job = command(owner, root, program, capture_stdout=True)
        job.start()
        assert done(job).phase == "failed"
        assert job.view().error_code == error
        assert job.shutdown()
        reject("invalid_handle", job.stdout)


def test_large_stderr_and_uncaptured_stdout_do_not_accumulate(owned):
    owner, root = owned
    program = "import os; [(os.write(2,b'x'*65536),os.write(1,b'y'*65536)) for _ in range(128)]"
    job = command(owner, root, program)
    job.start()
    assert done(job).phase == "exited"
    assert job.shutdown()
    reject("invalid_handle", job.stdout)


def test_shutdown_is_bounded_waits_for_ignore_term_child_and_is_idempotent(owned):
    owner, root = owned
    ready = root / "ready"
    program = (
        "import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"pathlib.Path({str(ready)!r}).write_text('ready');time.sleep(.4)"
    )
    job = command(owner, root, program)
    job.start()
    until(ready.exists)
    begin = time.monotonic()
    assert not job.shutdown(0.01)
    assert time.monotonic() - begin < 0.3
    assert job.view().resources_pending
    assert job.start().phase in ("stopping", "running")
    assert done(job).phase == "exited"
    assert job.shutdown(0)


def test_one_job_per_owner_and_lost_reference_stays_alive(owned):
    owner, root = owned
    first = command(owner, root, "import time;time.sleep(.4)")
    second = command(owner, root)
    first.start()
    reject("process_busy", second.start)
    reference = weakref.ref(first)
    del first
    gc.collect()
    assert reference() is not None and reference().view().resources_pending
    assert done(reference()).phase == "exited"
    second.start()
    assert done(second).phase == "exited"


def test_copy_and_fork_origin_before_mutex(owned, monkeypatch):
    owner, root = owned
    job = command(owner, root)
    for operation in (
        lambda: copy.copy(job),
        lambda: copy.deepcopy(job),
        lambda: pickle.dumps(job),
    ):
        with pytest.raises(TypeError):
            operation()
    pid = os.getpid()
    with monkeypatch.context() as changes:
        changes.setattr(os, "getpid", lambda: pid + 1)
        for operation in (job.view, job.start, job.shutdown, job.stdout):
            reject("invalid_handle", operation)
    assert job.shutdown()


@pytest.mark.parametrize("timeout", [-1, 6, True, float("nan"), float("inf"), "1"])
def test_invalid_shutdown_timeout(owned, timeout):
    owner, root = owned
    job = command(owner, root)
    reject("validation_error", lambda: job.shutdown(timeout))
    assert job.view().phase == "new"


@pytest.mark.parametrize(
    "arguments",
    [[], ("x\x00",), ("x\n",), ("x\u202e",), ("x" * 4097,), ("x",) * 129, ("x" * 4000,) * 5],
)
def test_invalid_arguments_do_not_reserve_slot(owned, arguments):
    owner, root = owned
    reject(
        "validation_error",
        lambda: api().OwnedCommand(owner, Path(sys.executable), arguments, cwd=root),
    )
    assert not (root / "analysis.slot").exists()


def test_repeated_commands_do_not_leak_descriptors(owned):
    owner, root = owned
    baseline = len(os.listdir("/dev/fd"))
    for _ in range(6):
        job = command(owner, root)
        job.start()
        assert done(job).phase == "exited"
        assert job.shutdown()
    assert len(os.listdir("/dev/fd")) <= baseline


def test_command_child_receives_only_fixed_environment(owned, monkeypatch):
    owner, root = owned
    monkeypatch.setenv("SYNTHETIC_PRIVATE_FLAG", "must_not_be_inherited")
    monkeypatch.setenv("PGSERVICE", "synthetic_service")
    job = command(
        owner,
        root,
        "import os;assert 'SYNTHETIC_PRIVATE_FLAG' not in os.environ;"
        "assert 'PGSERVICE' not in os.environ;print('ok')",
        capture_stdout=True,
    )
    job.start()
    assert done(job).phase == "exited" and job.stdout() == b"ok\n"


def isolated(tmp_path, body):
    prefix = (
        "import os,sys,time,subprocess,stat,threading\nfrom pathlib import Path\n"
        "from ara.docx_analysis_worker.macos import acquire_owner\n"
        "from ara.desktop.postgres_process import OwnedCommand\n"
        "root=Path(sys.argv[1]);root.mkdir(mode=0o700)\nowner=acquire_owner(root)\n"
        "job=OwnedCommand(owner,Path(sys.executable),('-I','-c',\"print('ok')\"),cwd=root)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", prefix + body, str(tmp_path.resolve() / "SYNTHETIC_PRIVATE")],
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONPATH": str(Path.cwd() / "src")},
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0 and result.stdout == b"ok\n", "Isolated lifetime test failed"
    assert not result.stderr


@pytest.mark.parametrize("fault", ["spawn", "close", "wait", "thread"])
def test_unknown_native_outcomes_stay_quarantined(tmp_path, fault):
    bodies = {
        "spawn": (
            "original=subprocess.Popen;lost=[]\n"
            "def broken(*a,**kw):\n p=original(*a,**kw);lost.append(p);"
            "raise OSError('synthetic unknown spawn')\n"
            "subprocess.Popen=broken\n"
        ),
        "close": (
            "original=os.close;fired=[]\n"
            "def broken(fd):\n"
            " if not fired and threading.current_thread().name=='aira-pg-owner' "
            "and stat.S_ISFIFO(os.fstat(fd).st_mode):\n"
            "  fired.append(True);original(fd);raise OSError('synthetic unknown close')\n"
            " return original(fd)\n"
            "os.close=broken\n"
        ),
        "wait": (
            "original=os.waitpid;fired=[]\n"
            "def broken(pid,options):\n"
            " result=original(pid,options)\n"
            " if result[0] and threading.current_thread().name=='aira-pg-owner' and not fired:\n"
            "  fired.append(True);raise OSError('synthetic unknown wait')\n"
            " return result\n"
            "os.waitpid=broken\n"
        ),
        "thread": (
            "def broken(self):\n raise RuntimeError('synthetic unknown thread start')\n"
            "threading.Thread.start=broken\n"
        ),
    }
    isolated(
        tmp_path,
        bodies[fault]
        + "job.start()\nend=time.monotonic()+8\n"
        + "while job.view().phase!='failed' and time.monotonic()<end: time.sleep(.01)\n"
        + "assert job.view().phase=='failed' and job.view().resources_pending\n"
        + "assert job.shutdown(.1) is False\n"
        + ("assert fired\n" if fault in ("close", "wait") else "")
        + ("[p.wait(timeout=5) for p in lost]\n" if fault == "spawn" else "")
        + "print('ok')\n",
    )
