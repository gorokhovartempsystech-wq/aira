"""Additional lifecycle ownership and native boundary review cases."""

import asyncio
import importlib
import socket
import threading
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from test_desktop_server import Application, api, license_client, ready, reject, wait_for
from test_desktop_server import world as world


@pytest.mark.parametrize("shared", ["app", "client"])
def test_exclusive_claim_covers_each_resource(world, shared):
    w = world
    ready(w)
    second_client = license_client(w["root"] / "second")
    app = w["app"] if shared == "app" else Application()
    client = w["client"] if shared == "client" else second_client
    other = api().LoopbackServer(app, client)
    reject("runtime_in_use", other.start)
    assert other.shutdown(timeout=0)
    assert second_client.view().phase == "new"
    assert w["client"].view().phase != "closed"
    second_client.close()


def test_failed_app_cleanup_keeps_quarantine(world):
    w = world
    w["app"].failure = "startup"
    w["host"].start()
    wait_for(lambda: not w["host"].view().resources_pending)
    client = license_client(w["root"] / "second")
    other = api().LoopbackServer(w["app"], client)
    reject("runtime_in_use", other.start)
    assert other.shutdown(timeout=0) and client.view().phase == "new"
    client.close()


def test_connection_is_detached_and_terminal_start_never_restarts(world):
    w = world
    first = ready(w)
    second = w["host"].connection()
    assert first == second and first is not second
    with pytest.raises(FrozenInstanceError):
        first.origin = "http://127.0.0.1:1"
    assert w["host"].shutdown(timeout=5)
    assert w["host"].start().phase == "closed"
    assert w["app"].trace == ["startup", "shutdown"]


@pytest.mark.parametrize("failure", ["construct", "start"])
def test_thread_launch_failure_releases_unstarted_application(world, monkeypatch, failure):
    w = world
    runtime = importlib.import_module("ara.desktop.server._runtime")

    def broken(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        if failure == "construct":
            patch.setattr(runtime.threading, "Thread", broken)
        else:
            patch.setattr(threading.Thread, "start", broken)
        w["host"].start()
        status = w["host"].view()
        assert status.phase == "failed" and status.error_code == "server_error"
        assert not status.resources_pending and not w["app"].trace
    assert w["client"].view().phase == "closed"
    other = api().LoopbackServer(w["app"], license_client(w["root"] / "second"))
    try:
        other.start()
        wait_for(lambda: other.view().phase == "ready")
    finally:
        assert other.shutdown(timeout=5)


def test_large_integer_timeout_is_fixed_validation_error(world):
    reject("validation_error", lambda: world["host"].shutdown(timeout=10**1000))
    assert world["host"].view().phase == "new"


def test_windows_socket_uses_exclusive_bind_without_reuse(monkeypatch):
    module = importlib.import_module("ara.desktop.server._server")
    calls = []
    sock = SimpleNamespace(
        set_inheritable=lambda value: calls.append(("inherit", value)),
        setsockopt=lambda *args: calls.append(("option", *args)),
        bind=lambda address: calls.append(("bind", address)),
    )
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    module.prepare_socket(sock)
    assert calls == [
        ("inherit", False),
        ("option", socket.SOL_SOCKET, -5, 1),
        ("bind", ("127.0.0.1", 0)),
    ]


@pytest.mark.parametrize("failure", ["bad_ack", "duplicate", "early_return", "system_exit"])
def test_lifespan_protocol_failures_never_publish_ready(tmp_path, failure, caplog, capsys):
    async def application(scope, receive, send):
        await receive()
        if failure == "bad_ack":
            await send({"type": "lifespan.shutdown.complete"})
        elif failure == "duplicate":
            await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.startup.complete"})
        elif failure == "system_exit":
            raise SystemExit("SYNTHETIC_PRIVATE")

    host = api().LoopbackServer(application, license_client(tmp_path / "license"))
    host.start()
    wait_for(lambda: not host.view().resources_pending)
    assert host.view().phase == "failed" and host.view().error_code == "lifespan_error"
    assert host.connection() is None and not host.shutdown(timeout=0)
    assert "SYNTHETIC_PRIVATE" not in caplog.text + repr(capsys.readouterr())


def test_shutdown_complete_still_waits_for_application_finally(tmp_path):
    acknowledged, release = threading.Event(), threading.Event()
    cancelled = []

    async def application(scope, receive, send):
        await receive()
        await send({"type": "lifespan.startup.complete"})
        await receive()
        await send({"type": "lifespan.shutdown.complete"})
        acknowledged.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.002)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    host = api().LoopbackServer(application, license_client(tmp_path / "license"))
    try:
        host.start()
        wait_for(lambda: host.view().phase == "ready")
        assert not host.shutdown(timeout=0.02)
        assert acknowledged.wait(3)
        assert host.view().resources_pending and not host.view().clean_shutdown
        assert not cancelled
    finally:
        release.set()
        assert host.shutdown(timeout=5)
    assert not cancelled


@pytest.mark.parametrize("failure", ["system_exit", "early_return"])
def test_abnormal_server_exit_drains_before_application_shutdown(world, monkeypatch, failure):
    w = world
    runtime = importlib.import_module("ara.desktop.server._runtime")
    trace = []

    class Server:
        started = False
        drained = False
        servers = []

        async def serve(self, sockets):
            trace.append("serve")
            if failure == "system_exit":
                raise SystemExit("SYNTHETIC_PRIVATE")

        async def shutdown(self, sockets):
            assert not w["app"].stopping.is_set()
            trace.append("drain")
            self.drained = True

    monkeypatch.setattr(runtime, "make_server", lambda *args: Server())
    w["host"].start()
    wait_for(lambda: not w["host"].view().resources_pending)
    assert trace == ["serve", "drain"]
    assert w["app"].trace == ["startup", "shutdown"]
    assert w["host"].view().error_code == "server_error"
    assert w["host"].connection() is None
