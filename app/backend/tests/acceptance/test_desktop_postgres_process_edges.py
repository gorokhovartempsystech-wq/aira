"""Review: startup outcome races, descendants, concurrency and strict status JSON."""

import importlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_desktop_postgres_process as base

owned = base.owned
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Darwin lifetime review")


def test_thread_start_failure_after_worker_exit_keeps_owner_claim(tmp_path):
    base.isolated(
        tmp_path,
        "original=threading.Thread.start\n"
        "def broken(self):\n original(self);self.join(5);raise RuntimeError('unknown return')\n"
        "threading.Thread.start=broken\njob.start()\n"
        "assert job.view().phase=='failed' and job.view().resources_pending\n"
        "next_job=OwnedCommand(owner,Path(sys.executable),('-I','-c',\"print('next')\"),cwd=root)\n"
        "try:\n next_job.start()\n"
        "except Exception as error:\n assert error.code=='process_busy'\n"
        "else:\n raise AssertionError('Owner claim was released before startup settled')\n"
        "print('ok')\n",
    )


def test_thread_construction_failure_is_fixed_and_retained(tmp_path):
    base.isolated(
        tmp_path,
        "def broken(self,*a,**kw):\n raise RuntimeError('synthetic thread constructor')\n"
        "threading.Thread.__init__=broken\n"
        "job.start()\nassert job.view().phase=='failed' and job.view().resources_pending\n"
        "assert not job.shutdown(0)\nprint('ok')\n",
    )


def test_descendant_slot_outlives_reaped_command(owned):
    owner, root = owned
    ready, release = root / "ready", root / "release"
    descendant = (
        "import pathlib,time\n"
        f"ready=pathlib.Path({str(ready)!r});release=pathlib.Path({str(release)!r})\n"
        "ready.write_text('ready');end=time.monotonic()+5\n"
        "while not release.exists() and time.monotonic()<end:time.sleep(.01)\n"
    )
    program = (
        "import sys,subprocess;"
        f"subprocess.Popen([sys.executable,'-I','-c',{descendant!r}],close_fds=False,"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
    )
    job = base.command(owner, root, program)
    job.start()
    try:
        base.until(ready.exists)
        assert not job.shutdown(0.1)
        assert job.view().resources_pending
        another = base.command(owner, root)
        base.reject("process_busy", another.start)
    finally:
        release.write_text("release")
        assert job.shutdown(5)
    assert job.view().phase == "exited"


def test_concurrent_stop_waiters_do_not_hold_state_mutex(owned):
    owner, root = owned
    ready = root / "ready"
    program = (
        "import signal,pathlib,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"pathlib.Path({str(ready)!r}).write_text('ready');time.sleep(.5)"
    )
    job = base.command(owner, root, program)
    job.start()
    base.until(ready.exists)
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: job.shutdown(0.01), range(4)))
    assert replies == [False] * 4
    assert job.shutdown(5)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_status_values_are_not_coerced_to_success(constant):
    wire = importlib.import_module("ara.desktop.postgres_process._wire")
    reader = wire.StatusReader()
    reader.feed(b'{"event":"started"}\n')
    raw = (
        json.dumps(
            dict(event="finished", returncode=0, error_code="REPLACE", stdout="", uncertain=False)
        )
        .replace('"REPLACE"', constant)
        .encode()
        + b"\n"
    )
    base.reject("protocol_error", lambda: reader.feed(raw))


def test_status_limit_and_duplicate_fields_are_rejected():
    wire = importlib.import_module("ara.desktop.postgres_process._wire")
    base.reject("protocol_error", lambda: wire.StatusReader().feed(b"x" * 100001))
    base.reject(
        "protocol_error",
        lambda: wire.StatusReader().feed(b'{"event":"started","event":"started"}\n'),
    )
