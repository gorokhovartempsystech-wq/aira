"""Independent native loopback lifetime acceptance; synthetic license ports only."""

import asyncio
import copy
import importlib
import json
import os
import pickle
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from test_licensing_client_runtime import Clock, Transport, done
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import DEVICE, synthetic_key

from ara.licensing.client import ActivationStore, LicenseClient

D = "/docx-documents/10000000-0000-0000-0000-000000000001"


def api():
    return importlib.import_module("ara.desktop.server")


def wait_for(check, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(0.005)
    raise AssertionError("Host fixture transition timed out")


def reject(code, call):
    with pytest.raises(api().HostError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


class Application:
    def __init__(self):
        self.start_gate, self.stop_gate, self.http_gate = (threading.Event() for _ in range(3))
        for gate in (self.start_gate, self.stop_gate, self.http_gate):
            gate.set()
        self.started, self.stopping, self.request_entered = (threading.Event() for _ in range(3))
        self.trace, self.requests, self.writes = [], [], []
        self.failure = None
        self.cancelled = False
        self.loop = None

    async def gate(self, event):
        while not event.is_set():
            await asyncio.sleep(0.002)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            self.loop = asyncio.get_running_loop()
            assert (await receive())["type"] == "lifespan.startup"
            self.trace.append("startup")
            self.started.set()
            await self.gate(self.start_gate)
            if self.failure == "startup":
                await send(dict(type="lifespan.startup.failed", message="SYNTHETIC_PRIVATE"))
                return
            if self.failure == "exception":
                raise ValueError("SYNTHETIC_PRIVATE")
            scope["state"]["shared"] = []
            await send(dict(type="lifespan.startup.complete"))
            if self.failure == "early_return":
                return
            assert (await receive())["type"] == "lifespan.shutdown"
            self.trace.append("shutdown")
            self.stopping.set()
            await self.gate(self.stop_gate)
            if self.failure == "shutdown":
                await send(dict(type="lifespan.shutdown.failed", message="SYNTHETIC_PRIVATE"))
            else:
                await send(dict(type="lifespan.shutdown.complete"))
            return
        assert asyncio.get_running_loop() is self.loop
        assert "request_only" not in scope["state"]
        scope["state"]["request_only"] = True
        scope["state"]["shared"].append(True)
        self.requests.append(scope)
        data = bytearray()
        while True:
            message = await receive()
            assert message["type"] == "http.request"
            data.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        self.request_entered.set()
        try:
            await self.gate(self.http_gate)
            self.writes.append(bytes(data))
            await send(
                dict(
                    type="http.response.start",
                    status=200,
                    headers=[(b"content-type", b"application/json")],
                )
            )
            await send(
                dict(
                    type="http.response.body",
                    body=json.dumps(
                        {"shared": len(scope["state"]["shared"]), "size": len(data)}
                    ).encode(),
                )
            )
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def license_client(root):
    return LicenseClient(
        ORIGIN,
        ActivationStore(root),
        clock=Clock(),
        transport=Transport(),
        device_provider=lambda: DEVICE,
    )


@pytest.fixture
def world(tmp_path):
    app = Application()
    client = license_client(tmp_path / "license")
    host = api().LoopbackServer(app, client)
    yield dict(app=app, client=client, host=host, root=tmp_path)
    for gate in (app.start_gate, app.stop_gate, app.http_gate):
        gate.set()
    host.shutdown(timeout=5)
    assert not host.view().resources_pending
    client.close()


def ready(w):
    assert w["host"].start().phase == "starting"
    wait_for(lambda: w["host"].view().phase == "ready")
    connection = w["host"].connection()
    assert connection is not None
    return connection


def http_for(connection):
    return httpx.Client(
        base_url=connection.origin,
        timeout=5,
        trust_env=False,
        headers={"X-AIRA-Session": connection.session_token.hex()},
    )


def activate(http, w):
    wait_for(lambda: w["client"].view().phase != "checking")
    assert (
        http.post("/desktop/license/activate", json={"license_key": synthetic_key()}).status_code
        == 202
    )
    assert done(w["client"]).phase == "active"


def test_factory_inert_and_empty_shutdown_does_not_take_client_ownership(world, monkeypatch):
    w = world
    assert w["host"].view().phase == "new" and w["host"].connection() is None
    assert not w["app"].trace and w["client"].view().phase == "new"

    def forbidden(*args, **kwargs):
        raise AssertionError("Factory performed external work")

    with monkeypatch.context() as patch:
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(threading.Thread, "start", forbidden)
        another = api().LoopbackServer(w["app"], w["client"])
        assert another.shutdown(timeout=0)
        assert another.view().phase == "closed"
    assert w["client"].view().phase == "new"


def test_real_server_fresh_check_exact_origin_and_lifespan_state(world):
    w = world
    connection = ready(w)
    assert connection.origin.startswith("http://127.0.0.1:")
    assert type(connection.session_token) is bytes and len(connection.session_token) == 32
    assert connection.session_token.hex() not in repr(connection) + repr(w["host"]) + repr(
        w["host"].view()
    )
    assert w["host"].start().phase == "ready"
    with http_for(connection) as http:
        assert http.get("/desktop/license").status_code == 200
        assert http.get(D).status_code == 403
        activate(http, w)
        assert http.get(D).json() == {"shared": 1, "size": 0}
        assert http.get(D).json() == {"shared": 2, "size": 0}
        assert http.get(D, headers={"Origin": "https://evil.invalid"}).status_code == 403
        assert http.get("/documents").status_code == 404
        assert b"x-aira-session" not in dict(w["app"].requests[-1]["headers"])
    assert w["host"].shutdown(timeout=5)
    assert w["host"].view().phase == "closed" and w["host"].view().clean_shutdown
    assert w["host"].connection() is None and w["client"].view().phase == "closed"
    assert w["app"].trace == ["startup", "shutdown"]
    with httpx.Client(timeout=0.5, trust_env=False) as http:
        with pytest.raises(httpx.ConnectError):
            http.get(connection.origin + "/desktop/license")


def test_shutdown_waits_for_accepted_write_then_lifespan(world):
    w = world
    connection = ready(w)
    with http_for(connection) as http, ThreadPoolExecutor(max_workers=1) as pool:
        activate(http, w)
        w["app"].http_gate.clear()
        future = pool.submit(
            http.post,
            D + "/import",
            content=b"kept",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert w["app"].request_entered.wait(3)
        assert not w["host"].shutdown(timeout=0.02)
        assert w["host"].view().resources_pending and w["host"].connection() is None
        assert not w["app"].stopping.is_set() and not w["app"].cancelled
        assert w["app"].writes == []
        w["app"].http_gate.set()
        assert future.result(timeout=4).status_code == 200
    assert w["host"].shutdown(timeout=5)
    assert w["app"].writes == [b"kept"] and not w["app"].cancelled
    assert w["app"].trace == ["startup", "shutdown"]


def test_late_startup_after_stop_never_publishes_ready(world):
    w = world
    w["app"].start_gate.clear()
    w["host"].start()
    assert w["app"].started.wait(3)
    assert not w["host"].shutdown(timeout=0.02)
    assert w["host"].view().phase == "stopping" and w["host"].connection() is None
    w["app"].start_gate.set()
    assert w["host"].shutdown(timeout=5)
    assert w["app"].trace == ["startup", "shutdown"] and not w["app"].requests


def test_startup_timeout_keeps_owner_until_late_cleanup(world, monkeypatch):
    m = importlib.import_module("ara.desktop.server._runtime")
    monkeypatch.setattr(m, "STARTUP_TIMEOUT", 0.04)
    w = world
    w["app"].start_gate.clear()
    w["host"].start()
    wait_for(lambda: w["host"].view().error_code == "startup_timeout")
    assert w["host"].view().resources_pending and w["host"].connection() is None
    assert not w["host"].shutdown(timeout=0)
    w["app"].start_gate.set()
    assert w["host"].shutdown(timeout=5)
    assert w["host"].view().phase == "failed" and w["host"].view().clean_shutdown


@pytest.mark.parametrize("failure", ["startup", "exception", "early_return", "shutdown"])
def test_lifespan_failure_safe_and_not_false_clean(world, failure, capsys, caplog):
    w = world
    w["app"].failure = failure
    w["host"].start()
    if failure == "shutdown":
        wait_for(lambda: w["host"].view().phase == "ready")
        w["host"].shutdown(timeout=5)
    wait_for(lambda: not w["host"].view().resources_pending)
    status = w["host"].view()
    assert status.phase == "failed" and status.error_code == "lifespan_error"
    assert not status.clean_shutdown and not w["host"].shutdown(timeout=0)
    assert w["host"].connection() is None
    assert "SYNTHETIC_PRIVATE" not in capsys.readouterr().out + caplog.text + repr(status)


def test_hung_shutdown_is_pending_not_success(world):
    w = world
    ready(w)
    w["app"].stop_gate.clear()
    assert not w["host"].shutdown(timeout=0.02)
    assert w["app"].stopping.wait(3)
    assert w["host"].view().resources_pending and not w["host"].view().clean_shutdown
    w["app"].stop_gate.set()
    assert w["host"].shutdown(timeout=5)


def test_same_app_client_cannot_be_owned_twice(world):
    w = world
    connection = ready(w)
    other = api().LoopbackServer(w["app"], w["client"])
    reject("runtime_in_use", other.start)
    assert other.shutdown(timeout=0)
    assert w["client"].view().phase != "closed" and w["host"].connection() == connection


def test_bind_failure_does_not_start_app_or_leak_claim(world, monkeypatch):
    w = world

    def broken(*args, **kwargs):
        raise OSError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(socket.socket, "bind", broken)
        w["host"].start()
        wait_for(
            lambda: w["host"].view().phase == "failed" and not w["host"].view().resources_pending
        )
    assert not w["app"].trace
    assert w["host"].view().error_code == "server_error"
    assert w["client"].view().phase == "closed"
    fresh = api().LoopbackServer(w["app"], license_client(w["root"] / "fresh"))
    try:
        fresh.start()
        wait_for(lambda: fresh.view().phase == "ready")
    finally:
        assert fresh.shutdown(timeout=5)


@pytest.mark.parametrize("value", [-1, 6, True, None, float("inf"), float("nan")])
def test_shutdown_timeout_validated_without_side_effects(world, value):
    reject("validation_error", lambda: world["host"].shutdown(timeout=value))
    assert world["host"].view().phase == "new"


def test_host_not_copyable_or_usable_after_fork(world, monkeypatch):
    host = world["host"]
    for action in (
        lambda: copy.copy(host),
        lambda: copy.deepcopy(host),
        lambda: pickle.dumps(host),
    ):
        reject("invalid_handle", action)
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: -1)
        for action in (host.view, host.start, host.connection, lambda: host.shutdown(timeout=0)):
            reject("invalid_handle", action)


def test_already_used_license_not_taken(world):
    w = world
    w["client"].start()
    assert done(w["client"]).phase == "activation_required"
    reject("validation_error", w["host"].start)
    assert w["client"].view().phase == "activation_required" and not w["app"].trace
