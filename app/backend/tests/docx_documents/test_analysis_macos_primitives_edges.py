"""Additional C1D1 fault injection; only synthetic directories and handles."""

import importlib
import os
import sys
from pathlib import Path

import pytest

from tests.acceptance.test_docx_analysis_macos_primitives import (
    api,
    fake_clock,
    native,
    reject,
    root,
)

__all__ = ["native", "root"]


def test_clock_overflow_and_loader_failure_sticky(monkeypatch):
    fake_clock(monkeypatch, [1, 2**63, 2], numer=1, denom=1)
    clock = api().DarwinClock()
    assert clock.now_ns() == 1
    reject("clock_unavailable", clock.now_ns)
    reject("clock_unavailable", clock.now_ns)


def test_copied_attributes_do_not_issue_owner(native, root):
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    clone = object.__new__(api().RuntimeOwner)
    for name in type(owner).__slots__:
        setattr(clone, name, getattr(owner, name))
    try:
        reject("invalid_handle", clone.abandon)
        reject("invalid_handle", clone.reserve_slot)
        assert owner.release_slot(slot)
    finally:
        owner.abandon()


def test_slot_replacement_does_not_unlock_or_modify_replacement(native, root):
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    (root / "analysis.slot").rename(root / "old-slot")
    (root / "analysis.slot").write_bytes(b"synthetic")
    try:
        reject("runtime_unavailable", lambda: owner.release_slot(slot))
        assert slot.fileno() >= 0
        owner.abandon()
        assert (root / "analysis.slot").read_bytes() == b"synthetic"
    finally:
        owner.abandon()


def test_probe_failure_invalidates_only_released_slot(native, root, monkeypatch):
    impl = importlib.import_module("ara.docx_analysis_worker.macos._locks")
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    original = impl._lock_file

    def fail(*args, **kwargs):
        raise OSError("private-sentinel")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(impl, "_lock_file", fail)
            reject("runtime_unavailable", lambda: owner.release_slot(slot))
        reject("invalid_handle", slot.fileno)
        assert impl._lock_file is original
        new = owner.reserve_slot()
        assert owner.release_slot(new)
    finally:
        owner.abandon()


def test_close_error_does_not_retry_reused_descriptor(native, root, monkeypatch):
    owner = api().acquire_owner(root)
    slot = owner.reserve_slot()
    target = slot.fileno()
    original = os.close
    replacement = []

    def close(fd):
        original(fd)
        if fd == target and not replacement:
            new_fd = os.open(root / "replacement", os.O_CREAT | os.O_RDWR, 0o600)
            assert new_fd == target
            replacement.append(new_fd)
            raise InterruptedError("private-sentinel")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "close", close)
            reject("runtime_unavailable", owner.abandon)
            owner.abandon()
        assert os.fstat(replacement[0]).st_size == 0
        reject("invalid_handle", slot.fileno)
    finally:
        for fd in replacement:
            original(fd)
        owner.abandon()


def test_root_writable_ancestor_and_unsafe_slot_no_leaks(native, root):
    owner = api().acquire_owner(root)
    slot_path = root / "analysis.slot"
    slot_path.symlink_to(root / "missing")
    count = len(list(Path("/dev/fd").iterdir()))
    try:
        for _ in range(25):
            reject("runtime_unavailable", owner.reserve_slot)
        assert len(list(Path("/dev/fd").iterdir())) == count
    finally:
        owner.abandon()
    root.chmod(0o777)
    child = root / "nested"
    child.mkdir(mode=0o700)
    reject("runtime_unavailable", lambda: api().acquire_owner(child))


def test_platform_and_issue_checks(monkeypatch, root):
    monkeypatch.setattr(sys, "platform", "win32")
    reject("platform_unavailable", lambda: api().acquire_owner(root))
    for cls in (api().RuntimeOwner, api().SlotLease):
        with pytest.raises(TypeError):
            cls()
