"""Remaining D2 construction/cleanup and negative evidence checks."""

import errno
import os
from pathlib import Path

import pytest

from tests.acceptance.test_docx_analysis_macos_guardian import (
    BINDING,
    exercise,
    module,
    native,
    owned,
    root,
)
from tests.acceptance.test_docx_analysis_macos_primitives import api, reject

__all__ = ["native", "root"]


def test_unexpected_exception_and_invalid_signal_do_not_become_normal_stop(monkeypatch):
    child, calls = owned(monkeypatch, waits=[(321, 0)])
    child._signal(0)
    assert child.signal_error and child.hard_fault and not calls
    child._poll(1)
    assert child.exited and child.fault
    child.close()


def test_kqueue_permission_is_a_hard_fault(monkeypatch):
    child, _ = owned(monkeypatch, registration_error=True, waits=[(321, 9)])
    assert child.hard_fault and not child.signal_error
    child._poll(1, force=True)
    assert child.exited and child.hard_fault
    child.close()


@pytest.mark.parametrize("operation", ["pipe", "spawn"])
def test_failed_launch_closes_pipes_and_preserves_caller_slot(native, root, monkeypatch, operation):
    impl = module("_launch")
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    original = os.pipe
    count = len(list(Path("/dev/fd").iterdir()))
    calls = 0

    def pipe():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError(errno.EIO, "private-sentinel")
        return original()

    def spawn(*args, **kwargs):
        assert kwargs["env"] == {"LC_ALL": "C", "LANG": "C"}
        assert kwargs["shell"] is False and kwargs["close_fds"] is True
        assert slot.fileno() in kwargs["pass_fds"]
        raise OSError(errno.EIO, "private-sentinel")

    try:
        with monkeypatch.context() as patch:
            if operation == "pipe":
                patch.setattr(os, "pipe", pipe)
            else:
                patch.setattr(impl.subprocess, "Popen", spawn)
            reject(
                "runtime_unavailable",
                lambda: impl.launch_fixture_guardian(slot, BINDING, deadline_ns=100, lease_ns=99),
            )
        assert len(list(Path("/dev/fd").iterdir())) == count
        assert os.fstat(slot.fileno()).st_size == 0
        assert owner.release_slot(slot)
    finally:
        owner.abandon()


def test_invalid_local_config_does_not_spawn(native, root, monkeypatch):
    impl = module("_launch")
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()

    def forbidden(*a, **k):
        raise AssertionError("unexpected spawn")

    try:
        monkeypatch.setattr(impl.subprocess, "Popen", forbidden)
        for options in (dict(mode="arbitrary"), dict(lease_ns=True), dict(deadline_ns=-1)):
            values = dict(deadline_ns=100, lease_ns=99) | options
            reject(
                "validation_error", lambda: impl.launch_fixture_guardian(slot, BINDING, **values)
            )
        assert owner.release_slot(slot)
    finally:
        owner.abandon()


def test_explicit_protocol_stop_is_crashed(native, root, monkeypatch):
    impl = module("_guardian")
    # Test-only child entry injects a valid protocol-stop after GO using the existing
    # deterministic wrapper; no new executable selection is exposed to the product.
    from tests.acceptance.test_docx_analysis_macos_stop_outcome import WRAPPER

    entry = root.parent / "protocol.py"
    source = (
        "SOURCE_ROOT="
        + repr(str(Path(__file__).resolve().parents[2] / "src"))
        + "\nREPORT_PATH="
        + repr(str(root.parent / "meta.json"))
        + "\nCASE='prepared'\n"
        + WRAPPER.replace("'reason':'user'", "'reason':'protocol'")
    )
    entry.write_text(source)
    monkeypatch.setattr(module("_launch"), "ENTRY", entry)
    _, _, status, code = exercise(root)
    assert code == 0 and status.values["exit_kind"] == "crashed"
    assert status.values["cleanup_confirmed"]
    assert (
        impl._closed_kind(
            exited=True,
            lost=False,
            exit_code=0,
            hard_fault=True,
            stop_requested=True,
            signal_error=True,
        )
        == "crashed"
    )


def test_late_drain_fault_overrides_signal_race_stop(native, root, monkeypatch):
    from tests.acceptance.test_docx_analysis_macos_stop_outcome import WRAPPER

    entry = root.parent / "drain.py"
    source = (
        "SOURCE_ROOT="
        + repr(str(Path(__file__).resolve().parents[2] / "src"))
        + "\nREPORT_PATH="
        + repr(str(root.parent / "meta.json"))
        + "\nCASE='signal'\n"
        + WRAPPER.replace(
            "return real_read(fd,size)",
            "if facts['signals'] and fd!=control and size==65536:\n"
            "        raise OSError(errno.EIO,'synthetic')\n"
            "    return real_read(fd,size)",
        )
    )
    entry.write_text(source)
    monkeypatch.setattr(module("_launch"), "ENTRY", entry)
    _, _, status, code = exercise(root, "wait", "stop")
    assert code == 0 and status.values["exit_kind"] == "crashed"
    assert status.values["cleanup_confirmed"]
