"""Complete bounded request envelopes before application/database dispatch."""

import asyncio
import importlib
import secrets

import pytest
from test_desktop_access import LOCAL, D, Q, S, exchange, json_headers
from test_desktop_server import license_client
from test_licensing_client_runtime import done
from test_licensing_policy import synthetic_key

from ara.desktop.access import LicensedApplication


def module():
    return importlib.import_module("ara.desktop.server._body")


class Echo:
    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        message = await receive()
        self.calls.append((scope, message))
        await send(dict(type="http.response.start", status=200, headers=[]))
        await send(dict(type="http.response.body", body=b'{"fixture":true}'))


@pytest.fixture
def world(tmp_path):
    client = license_client(tmp_path)
    client.start(synthetic_key())
    assert done(client).phase == "active"
    inner = Echo()
    state = {"shared": []}
    envelope = module().BodyEnvelope(inner, state)
    token = secrets.token_bytes(32)
    app = LicensedApplication(envelope, client, origin=LOCAL, session_token=token)
    yield dict(app=app, inner=inner, state=state, token=token, client=client)
    client.close()


def call(w, *args, **kwargs):
    return asyncio.run(exchange(w, *args, **kwargs))


def test_exact_binary_replay_once_and_shallow_state(world):
    data = b"\x00\xffSynthetic bytes"
    messages = [
        dict(type="http.request", body=data[:3], more_body=True),
        dict(type="http.request", body=data[3:], more_body=False),
    ]

    async def receive():
        return messages.pop(0)

    headers = json_headers(world)[:2] + [
        (b"content-type", b"application/octet-stream"),
        (b"content-length", str(len(data)).encode()),
    ]
    assert call(world, D + "/import", "POST", headers=headers, receive=receive)[0] == 200
    scope, message = world["inner"].calls[0]
    assert message == dict(type="http.request", body=data, more_body=False)
    assert (
        scope["state"] is not world["state"]
        and scope["state"]["shared"] is world["state"]["shared"]
    )
    assert dict(scope["headers"])[b"content-type"] == b"application/octet-stream"
    assert messages == []


@pytest.mark.parametrize(
    "path,length", [(D + "/import", 33554433), (S + "/commands", 8388609), (S + "/save", 65537)]
)
def test_existing_byte_caps_checked_before_inner(world, path, length):
    response = call(
        world, path, "POST", headers=json_headers(world, (b"content-length", str(length).encode()))
    )
    assert response[0] == 413 and not world["inner"].calls


@pytest.mark.parametrize(
    "kind",
    [
        "get_body",
        "create_body",
        "length_mismatch",
        "duplicate_length",
        "transfer_conflict",
        "disconnect",
        "encoding",
    ],
)
def test_bad_body_never_reaches_application(world, kind):
    method, path, body = "POST", S + "/save", b"{}"
    headers = json_headers(world)
    receive = None
    status = 422
    if kind == "get_body":
        method, path = "GET", D
    elif kind == "create_body":
        path = D + "/create"
    elif kind == "length_mismatch":
        headers.append((b"content-length", b"3"))
    elif kind == "duplicate_length":
        headers.extend([(b"content-length", b"2")] * 2)
    elif kind == "transfer_conflict":
        headers.extend([(b"content-length", b"2"), (b"transfer-encoding", b"chunked")])
    elif kind == "encoding":
        headers.append((b"content-encoding", b"gzip"))
        status = 415
    else:

        async def receive():
            return dict(type="http.disconnect")

    assert call(world, path, method, body, headers=headers, receive=receive)[0] == status
    assert not world["inner"].calls


def test_frame_budget_is_finite_without_inner(world):
    frames = []

    async def receive():
        frames.append(True)
        return dict(type="http.request", body=b"", more_body=True)

    assert call(world, S + "/save", "POST", headers=json_headers(world), receive=receive)[0] == 422
    assert len(frames) == 32768 and not world["inner"].calls


def test_total_body_timeout_not_renewed_per_chunk(world, monkeypatch):
    monkeypatch.setattr(module(), "BODY_TIMEOUT", 0.04)

    async def receive():
        await asyncio.sleep(0.025)
        return dict(type="http.request", body=b" ", more_body=True)

    assert call(world, S + "/save", "POST", headers=json_headers(world), receive=receive)[0] == 408
    assert not world["inner"].calls
    assert call(world, D)[0] == 200


def test_two_ordinary_slots_preserve_stop_and_license_poll(world):
    async def scenario():
        entered = []
        release = asyncio.Event()

        async def receive():
            entered.append(True)
            await release.wait()
            return dict(type="http.request", body=b"{}", more_body=False)

        tasks = [
            asyncio.create_task(
                exchange(world, S + "/save", "POST", headers=json_headers(world), receive=receive)
            )
            for _ in range(2)
        ]
        try:
            for _ in range(100):
                if len(entered) == 2:
                    break
                await asyncio.sleep(0.001)
            assert len(entered) == 2
            assert (await exchange(world, D))[0] == 503
            assert (await exchange(world, Q + "/stop", "POST", b"{}", headers=json_headers(world)))[
                0
            ] == 200
            assert (await exchange(world))[0] == 200
        finally:
            release.set()
        assert all(r[0] == 200 for r in await asyncio.gather(*tasks))

    asyncio.run(scenario())


def test_cancelled_prefetch_has_no_app_effect_and_releases_slot(world):
    async def scenario():
        entered = asyncio.Event()

        async def receive():
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            exchange(world, S + "/save", "POST", headers=json_headers(world), receive=receive)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not world["inner"].calls
        assert (await exchange(world, D))[0] == 200

    asyncio.run(scenario())
