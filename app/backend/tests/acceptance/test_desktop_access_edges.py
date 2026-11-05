"""Review additions: cancellation, real loopback HTTP and response ownership."""

import asyncio
import secrets
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from test_desktop_access import LOCAL, D, Inner, S, activate, api, call, exchange, json_headers
from test_desktop_access import world as world
from test_licensing_client_runtime import Clock, Transport, done
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import DEVICE, synthetic_key

from ara.licensing.client import ActivationStore, LicenseClient


def test_real_loopback_http_requires_current_capability_and_online_license(tmp_path):
    clock, transport = Clock(), Transport()
    client = LicenseClient(
        ORIGIN,
        ActivationStore(tmp_path),
        clock=clock,
        transport=transport,
        device_provider=lambda: DEVICE,
    )
    token = secrets.token_bytes(32)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
    wrapper = api().LicensedApplication(Inner(), client, origin=origin, session_token=token)
    server = uvicorn.Server(
        uvicorn.Config(
            wrapper,
            host="127.0.0.1",
            port=sock.getsockname()[1],
            loop="asyncio",
            lifespan="off",
            proxy_headers=False,
            access_log=False,
            log_config=None,
            log_level="critical",
        )
    )
    failures = []

    def serve():
        try:
            asyncio.run(server.serve(sockets=[sock]))
        except BaseException:
            failures.append(True)

    thread = threading.Thread(target=serve, name="desktop-http-fixture", daemon=True)
    thread.start()
    try:
        limit = time.monotonic() + 5
        while not server.started and not failures and time.monotonic() < limit:
            time.sleep(0.005)
        assert server.started and not failures
        with httpx.Client(base_url=origin, trust_env=False, timeout=3) as http:
            assert http.get("/desktop/license").status_code == 403
            http.headers["X-AIRA-Session"] = token.hex()
            assert http.get("/desktop/license").json()["phase"] == "new"
            assert http.get(D).status_code == 403
            assert http.get("/desktop/license", headers={"Host": "evil.invalid"}).status_code == 403
            assert (
                http.get("/desktop/license", headers={"Origin": "https://evil.invalid"}).status_code
                == 403
            )
            assert (
                http.post(
                    "/desktop/license/activate", json={"license_key": synthetic_key()}
                ).status_code
                == 202
            )
            assert done(client).phase == "active"
            assert http.get(D).json() == {"fixture": True}
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        client.close()
    assert not thread.is_alive() and not failures


def test_cancelled_body_requests_release_slots(world):
    async def scenario():
        entered = []

        async def receive():
            entered.append(True)
            await asyncio.Event().wait()

        tasks = [
            asyncio.create_task(
                exchange(
                    world,
                    "/desktop/license/verify",
                    "POST",
                    headers=json_headers(world),
                    receive=receive,
                )
            )
            for _ in range(4)
        ]
        for _ in range(100):
            if len(entered) == 4:
                break
            await asyncio.sleep(0.001)
        assert len(entered) == 4
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(value, asyncio.CancelledError) for value in results)
        assert (await exchange(world))[0] == 200

    asyncio.run(scenario())
    assert world["client"].view().phase == "new"


def test_partial_inner_response_not_replaced_and_exception_sanitized(world):
    activate(world)

    async def broken(scope, receive, send):
        await send(dict(type="http.response.start", status=200, headers=[]))
        await send(dict(type="http.response.body", body=b"partial", more_body=True))
        raise ValueError("SYNTHETIC_PRIVATE")

    wrapper = api().LicensedApplication(
        broken, world["client"], origin=LOCAL, session_token=world["token"]
    )
    sent = []

    async def scenario():
        async def receive():
            return dict(type="http.request", body=b"", more_body=False)

        async def send(message):
            sent.append(message)

        scope = dict(
            type="http",
            scheme="http",
            path=D,
            raw_path=D.encode(),
            method="GET",
            query_string=b"",
            headers=json_headers(world),
            server=("127.0.0.1", 8767),
            client=("127.0.0.1", 50000),
        )
        with pytest.raises(api().AccessError) as caught:
            await wrapper(scope, receive, send)
        assert caught.value.code == "local_error"
        assert "SYNTHETIC_PRIVATE" not in str(caught.value)

    asyncio.run(scenario())
    assert len([m for m in sent if m["type"] == "http.response.start"]) == 1
    assert "SYNTHETIC_PRIVATE" not in repr(sent)


def test_expiry_racing_status_does_not_create_preservation_authority(world, monkeypatch):
    activate(world)
    original = world["client"].view
    deadline = world["client"].require_active().deadline_ns

    def delayed():
        state = original()
        world["clock"].value = deadline
        return state

    monkeypatch.setattr(world["client"], "view", delayed)
    status, body, _, _ = call(world)
    assert status == 200 and body["phase"] == "expired" and not body["preservation_available"]
    assert call(world, D)[0] == 403


@pytest.mark.parametrize(
    "path",
    [
        S.replace("20000000", "00000000").replace("000000000001", "000000000000"),
        D + "/analysis-runs/00000000-0000-0000-0000-000000000000",
    ],
)
def test_zero_nested_identifiers_rejected(world, path):
    activate(world)
    assert call(world, path)[0] == 404
    assert not world["inner"].scopes


def test_factory_no_entropy_clock_file_or_network_calls(world, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Constructor performed I/O")

    with monkeypatch.context() as patch:
        patch.setattr(secrets, "token_bytes", forbidden)
        patch.setattr(socket, "socket", forbidden)
        patch.setattr(world["clock"], "now_ns", forbidden)
        wrapper = api().LicensedApplication(
            world["inner"], world["client"], origin=LOCAL, session_token=world["token"]
        )
        assert world["token"].hex() not in repr(wrapper)
    assert world["client"].view().phase == "new"
    assert not world["inner"].scopes
