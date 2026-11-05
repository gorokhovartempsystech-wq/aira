"""Known licensing worker completion, distinct from nonblocking access invalidation."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_licensing_client_runtime import done, world  # noqa: F401
from test_licensing_client_store import reject


def test_idle_and_completed_client_drain(world):  # noqa: F811
    client = world["client"]
    assert not client.resources_pending()
    client.start(world["key"])
    assert done(client).phase == "active"
    assert not client.resources_pending()
    assert client.shutdown(0)
    assert client.view().phase == "closed"
    assert client.shutdown(0)


@pytest.mark.parametrize("stage", ["transport", "store"])
def test_shutdown_waits_for_begun_io_without_late_access(world, monkeypatch, stage):  # noqa: F811
    client, store = world["client"], world["store"]
    entered, release = threading.Event(), threading.Event()
    if stage == "store":
        original = store.save

        def held(value):
            entered.set()
            assert release.wait(5)
            original(value)

        monkeypatch.setattr(store, "save", held)
    else:
        entered, release = world["transport"].entered, world["transport"].release
        release.clear()
    try:
        client.start(world["key"])
        assert entered.wait(3)
        before = time.monotonic()
        client.close()
        assert not client.shutdown(0.02)
        assert time.monotonic() - before < 0.3
        assert client.resources_pending()
        assert client.view().phase == "closed"
        reject("access_denied", client.require_active)
        reject("client_closed", client.start)
    finally:
        release.set()
    assert client.shutdown(3)
    assert not client.resources_pending()
    assert (store.load() is not None) == (stage == "store")
    reject("access_denied", client.require_active)


def test_close_while_thread_start_waits_cannot_publish_or_write(world, monkeypatch):  # noqa: F811
    client = world["client"]
    entered, release = threading.Event(), threading.Event()
    original = threading.Thread.start

    def held(thread):
        if thread.name == "aira-license-check":
            entered.set()
            assert release.wait(5)
        return original(thread)

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(threading.Thread, "start", held)
        future = pool.submit(client.start, world["key"])
        try:
            assert entered.wait(3)
            assert client.resources_pending()
            assert client.start(world["key"]).phase == "checking"
            reject("client_busy", client.start)
            assert not client.shutdown(0.02)
            assert client.view().phase == "closed"
        finally:
            release.set()
        assert future.result(timeout=3).phase == "closed"
    assert client.shutdown(3)
    assert not world["transport"].requests and world["store"].load() is None


@pytest.mark.parametrize("value", [-1, 6, True, None, float("inf"), float("nan"), 10**1000])
def test_invalid_budget_has_no_side_effect(world, value):  # noqa: F811
    client = world["client"]
    reject("validation_error", lambda: client.shutdown(value))
    assert client.view().phase == "new" and not client.resources_pending()


def test_pid_checked_before_inherited_mutex(world, monkeypatch):  # noqa: F811
    client = world["client"]
    with client._lock:
        with monkeypatch.context() as patch:
            patch.setattr(os, "getpid", lambda: -1)
            reject("invalid_handle", client.resources_pending)
            reject("invalid_handle", client.shutdown)


@pytest.mark.parametrize("failure", ["constructor", "before_start", "after_start"])
def test_ambiguous_launch_retained_even_after_worker_exit(world, monkeypatch, failure):  # noqa: F811
    # Quarantined clients contain only synthetic fixture ports, no native handles.
    client = world["client"]
    original = threading.Thread.start

    def broken(thread):
        if failure == "after_start":
            original(thread)
        raise OSError("SYNTHETIC_PRIVATE")

    def construct(*args, **kwargs):
        raise OSError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        if failure == "constructor":
            patch.setattr(threading, "Thread", construct)
        else:
            patch.setattr(threading.Thread, "start", broken)
        result = client.start(world["key"])
    assert result.phase == "failed" and result.error_code == "client_error"
    assert not result.retry_available and client.resources_pending()
    reject("client_busy", client.start)
    assert not client.shutdown(0.05)
    assert client.resources_pending() and client.view().phase == "closed"
    assert not world["transport"].requests and world["store"].load() is None
    assert "SYNTHETIC_PRIVATE" not in repr(result)
