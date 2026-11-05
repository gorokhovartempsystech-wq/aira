"""Client state machine with explicit synthetic device/clock/network ports."""

import copy
import os
import pickle
import threading
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_licensing_client_store import api, reject
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import BASE, DEVICE, OTHER, synthetic_key
from test_licensing_server import license_world  # noqa: F401

from ara import licensing as core


class Clock:
    def __init__(self):
        self.value = 1_000_000_000
        self.failed = False

    def now_ns(self):
        if self.failed:
            raise OSError("SYNTHETIC_PRIVATE")
        return self.value


class Transport:
    def __init__(self):
        self.id = uuid4()
        self.requests = []
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.failure = None
        self.mutate = lambda grant: grant

    def execute(self, req, checkpoint):
        self.requests.append(req)
        self.entered.set()
        assert self.release.wait(5), "Fixture worker was not released"
        if self.failure:
            raise self.failure
        grant = core.LaunchGrant(
            req.operation, self.id, req.device_id, req.nonce, BASE, BASE, BASE + 60000
        )
        return core.encode_grant(self.mutate(grant))


@pytest.fixture
def world(tmp_path):
    clock, transport = Clock(), Transport()
    store = api().ActivationStore(tmp_path / "identity")
    client = api().LicenseClient(
        ORIGIN, store, clock=clock, transport=transport, device_provider=lambda: DEVICE
    )
    value = dict(clock=clock, transport=transport, store=store, client=client, key=synthetic_key())
    yield value
    transport.release.set()
    client.close()


def done(client):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = client.view()
        if value.phase != "checking" and (value.retry_available or value.phase == "closed"):
            return value
        time.sleep(0.005)
    raise AssertionError("Fixture client did not drain")


def test_missing_identity_requires_key_without_network(world):
    w = world
    assert w["client"].view().phase == "new"
    w["client"].start()
    assert done(w["client"]).phase == "activation_required"
    assert w["transport"].requests == []
    reject("access_denied", w["client"].require_active)


def test_first_activation_reopen_requires_new_online_check(world):
    w = world
    w["client"].start(w["key"])
    first = done(w["client"])
    assert first.phase == "active" and first.license_id == w["transport"].id
    assert w["key"] not in repr(first) + repr(w["client"])
    permit = w["client"].require_active()
    assert permit.device_id == DEVICE
    w["client"].close()
    assert w["store"].load() == api().ActivationIdentity(w["transport"].id, DEVICE)
    client = api().LicenseClient(
        ORIGIN,
        w["store"],
        clock=w["clock"],
        transport=w["transport"],
        device_provider=lambda: DEVICE,
    )
    try:
        reject("access_denied", client.require_active)
        client.start()
        assert done(client).phase == "active"
        first, second = w["transport"].requests
        assert first.operation == "activate" and second.operation == "check"
        assert second.license_key is None and second.license_id == permit.license_id
        assert second.nonce != first.nonce
    finally:
        client.close()


def test_new_attempt_clears_access_and_network_failure_never_uses_cache(world):
    w = world
    w["client"].start(w["key"])
    assert done(w["client"]).phase == "active"
    w["transport"].release.clear()
    w["transport"].failure = api().ClientError("network_unavailable")
    w["client"].start()
    reject("access_denied", w["client"].require_active)
    w["transport"].release.set()
    result = done(w["client"])
    assert result.phase == "failed" and result.error_code == "network_unavailable"
    reject("access_denied", w["client"].require_active)


def test_wrong_local_device_never_sends_request(world):
    w = world
    w["store"].save(api().ActivationIdentity(uuid4(), OTHER))
    w["client"].start()
    assert done(w["client"]).error_code == "device_mismatch"
    assert not w["transport"].requests


def test_double_click_one_worker_different_intent_busy(world):
    w = world
    w["transport"].release.clear()
    first = w["client"].start(w["key"])
    assert w["transport"].entered.wait(3)
    assert first.phase == "checking"
    assert w["client"].start(w["key"].lower()).phase == "checking"
    reject("client_busy", lambda: w["client"].start(synthetic_key()))
    assert len(w["transport"].requests) == 1
    w["transport"].release.set()
    assert done(w["client"]).phase == "active"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda g: replace(g, nonce="d" * 64),
        lambda g: replace(g, device_id=OTHER),
        lambda g: replace(g, operation="check"),
    ],
)
def test_foreign_response_cannot_activate(world, mutation):
    w = world
    w["transport"].mutate = mutation
    w["client"].start(w["key"])
    assert done(w["client"]).error_code == "invalid_response"
    assert w["store"].load() is None


def test_timeout_bounds_worker_count_and_late_result_has_no_access_or_write(world):
    w = world
    w["transport"].release.clear()
    w["client"].start(w["key"])
    assert w["transport"].entered.wait(3)
    w["clock"].value += 15_000_000_001
    value = w["client"].view()
    assert value.phase == "failed" and value.error_code == "verification_timeout"
    assert not value.retry_available
    for _ in range(5):
        reject("client_busy", lambda: w["client"].start())
    assert len(w["transport"].requests) == 1
    w["transport"].release.set()
    assert done(w["client"]).error_code == "verification_timeout"
    assert w["store"].load() is None
    reject("access_denied", w["client"].require_active)


def test_close_is_nonblocking_and_prevents_late_result(world):
    w = world
    w["transport"].release.clear()
    w["client"].start(w["key"])
    assert w["transport"].entered.wait(3)
    before = time.monotonic()
    w["client"].close()
    assert time.monotonic() - before < 0.2
    assert w["client"].view().phase == "closed"
    reject("client_closed", lambda: w["client"].start(w["key"]))
    w["transport"].release.set()
    time.sleep(0.05)
    assert w["store"].load() is None
    reject("access_denied", w["client"].require_active)


def test_expiry_including_suspend_uses_continuous_clock(world):
    w = world
    w["client"].start(w["key"])
    assert done(w["client"]).phase == "active"
    permit = w["client"].require_active()
    w["clock"].value = permit.deadline_ns - 1
    assert w["client"].require_active() == permit
    w["clock"].value += 1
    reject("license_expired", w["client"].require_active)
    assert w["client"].view().phase == "expired"


@pytest.mark.parametrize("failure", ["exception", "backward", "bool"])
def test_unreliable_clock_closes_access(world, failure):
    w = world
    w["client"].start(w["key"])
    assert done(w["client"]).phase == "active"
    if failure == "exception":
        w["clock"].failed = True
    else:
        w["clock"].value = 0 if failure == "backward" else True
    assert w["client"].view().error_code == "clock_unavailable"
    reject("access_denied", w["client"].require_active)


def test_save_failure_denies_access_and_check_never_rewrites(world, monkeypatch):
    w = world

    def fail(*_):
        raise OSError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(w["store"], "save", fail)
        w["client"].start(w["key"])
        assert done(w["client"]).error_code == "activation_store_error"
        reject("access_denied", w["client"].require_active)
    w["store"].save(api().ActivationIdentity(w["transport"].id, DEVICE))
    monkeypatch.setattr(w["store"], "save", fail)
    w["client"].start()
    assert done(w["client"]).phase == "active"


def test_cancel_during_save_may_save_identity_but_never_access(world, monkeypatch):
    w = world
    entered, release = threading.Event(), threading.Event()
    original = w["store"].save

    def save(value):
        entered.set()
        assert release.wait(3)
        original(value)

    monkeypatch.setattr(w["store"], "save", save)
    w["client"].start(w["key"])
    try:
        assert entered.wait(3)
        w["client"].close()
    finally:
        release.set()
    deadline = time.monotonic() + 3
    while w["store"].load() is None and time.monotonic() < deadline:
        time.sleep(0.005)
    assert w["store"].load() is not None
    assert w["client"].view().phase == "closed"
    reject("access_denied", w["client"].require_active)


def test_runtime_cannot_cross_pid_copy_or_pickle(world, monkeypatch):
    client = world["client"]
    for operation in [
        lambda: copy.copy(client),
        lambda: copy.deepcopy(client),
        lambda: pickle.dumps(client),
    ]:
        reject("invalid_handle", operation)
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: -1)
        for operation in [client.view, client.start, client.require_active, client.close]:
            reject("invalid_handle", operation)


def test_constructor_does_no_io_and_errors_do_not_echo(tmp_path):
    calls = []

    class Port:
        def __getattr__(self, name):
            def forbidden(*args):
                calls.append(name)
                raise OSError("SYNTHETIC_PRIVATE")

            return forbidden

    port = Port()
    client = api().LicenseClient(
        ORIGIN, port, clock=port, transport=port, device_provider=lambda: calls.append("device")
    )
    assert not calls
    assert client.view().phase == "new"
    reject("validation_error", lambda: client.start("SYNTHETIC_PRIVATE"))
    assert not calls
    client.close()


def test_real_server_http_activation_restart_disable_and_no_renewal(license_world, tmp_path):  # noqa: F811
    w = license_world
    requests = []

    class InProcessFixtureTransport:
        def execute(self, req, checkpoint):
            checkpoint()
            requests.append(req)
            with TestClient(
                w["a"].create_license_app(w["runtime"]), base_url="https://fixture.invalid"
            ) as http:
                reply = http.post(
                    "/license/v1/" + req.operation,
                    content=core.encode_request(req),
                    headers={"Content-Type": "application/json"},
                )
            if reply.status_code != 200:
                raise api().ClientError(reply.json()["code"])
            return reply.content

    store, clock = api().ActivationStore(tmp_path / "activation"), Clock()
    for attempt in range(3):
        client = api().LicenseClient(
            ORIGIN,
            store,
            clock=clock,
            transport=InProcessFixtureTransport(),
            device_provider=lambda: DEVICE,
        )
        try:
            reject("access_denied", client.require_active)
            client.start(w["key"] if attempt == 0 else None)
            value = done(client)
            if attempt == 2:
                assert value.error_code == "license_disabled"
            else:
                assert value.phase == "active" and value.expires_at_ms == BASE + 60000
        finally:
            client.close()
        if attempt == 1:
            w["a"].set_enabled(w["runtime"], license_id=w["id"], enabled=False)
        w["clock"][0] += 1000
    assert [r.operation for r in requests] == ["activate", "check", "check"]
    assert len({r.nonce for r in requests}) == 3
    assert w["a"].get_license(w["runtime"], license_id=w["id"]).expires_at_ms == BASE + 60000
