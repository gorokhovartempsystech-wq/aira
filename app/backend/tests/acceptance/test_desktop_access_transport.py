"""Strict local licensing messages and bounded ASGI lifecycle."""

import asyncio
import json

import pytest
from test_desktop_access import LOCAL, D, S, activate, api, call, exchange, json_headers
from test_desktop_access import world as world
from test_licensing_client_runtime import done


@pytest.mark.parametrize(
    "body,headers,status",
    [
        (b"{}", [], 415),
        (b"{}", [(b"content-type", b"text/plain")], 415),
        (b"{}", [(b"content-type", b"application/json"), (b"content-encoding", b"gzip")], 415),
        (b"x" * 1025, [(b"content-type", b"application/json")], 413),
        (b"{", [(b"content-type", b"application/json")], 422),
        (b'{"license_key":"SYNTHETIC_PRIVATE"}', [(b"content-type", b"application/json")], 422),
        (b'{"x":NaN}', [(b"content-type", b"application/json")], 422),
        (b'{"x":1,"x":2}', [(b"content-type", b"application/json")], 422),
        (b"null", [(b"content-type", b"application/json")], 422),
        (b"\xff", [(b"content-type", b"application/json")], 422),
        (b"{}", [(b"content-type", b"application/json"), (b"content-length", b"3")], 422),
        (b"{}", [(b"content-type", b"application/json"), (b"content-length", b"-2")], 422),
        (
            b"{}",
            [
                (b"content-type", b"application/json"),
                (b"content-length", b"2"),
                (b"content-length", b"2"),
            ],
            422,
        ),
    ],
)
def test_invalid_license_payload_does_not_start_client(world, body, headers, status):
    w = world
    local_headers = json_headers(w)[:2] + headers
    response = call(w, "/desktop/license/verify", "POST", body, headers=local_headers)
    assert response[0] == status
    assert "SYNTHETIC_PRIVATE" not in json.dumps(response[1])
    assert w["client"].view().phase == "new" and not w["transport"].requests
    assert not w["inner"].scopes


def test_activation_exact_shape_no_key_in_inner_or_output(world):
    w = world
    for body in ({}, {"license_key": w["key"], "extra": True}, {"license_key": 123}):
        assert (
            call(
                w,
                "/desktop/license/activate",
                "POST",
                json.dumps(body).encode(),
                headers=json_headers(w),
            )[0]
            == 422
        )
    raw = ('{"license_key":"' + w["key"] + '","license_key":"' + w["key"] + '"}').encode()
    assert call(w, "/desktop/license/activate", "POST", raw, headers=json_headers(w))[0] == 422
    assert w["client"].view().phase == "new"
    assert call(w, body=b"unexpected")[0] == 422
    assert call(w, changes={"query_string": b"key=SYNTHETIC_PRIVATE"})[0] == 422
    assert not w["transport"].requests and not w["inner"].scopes


def test_failed_retry_keeps_preservation_but_fresh_client_denies(world):
    from ara.licensing.client import ClientError

    w = world
    activate(w)
    assert call(w, D)[0] == 200
    w["transport"].failure = ClientError("network_unavailable")
    assert call(w, "/desktop/license/verify", "POST", b"{}", headers=json_headers(w))[0] == 202
    assert done(w["client"]).phase == "failed"
    assert call(w, D)[0] == 200
    assert call(w, S + "/commands", "POST")[0] == 403


def test_four_body_slots_no_queue_and_timeout_releases_all(world, monkeypatch):
    module = __import__("ara.desktop.access._http", fromlist=["BODY_TIMEOUT"])
    monkeypatch.setattr(module, "BODY_TIMEOUT", 0.04)

    async def scenario():
        entered = []
        wait = asyncio.Event()

        async def slow():
            entered.append(True)
            await wait.wait()
            return dict(type="http.request", body=b"{}", more_body=False)

        jobs = [
            asyncio.create_task(
                exchange(
                    world,
                    "/desktop/license/verify",
                    "POST",
                    headers=json_headers(world),
                    receive=slow,
                )
            )
            for _ in range(4)
        ]
        for _ in range(100):
            if len(entered) == 4:
                break
            await asyncio.sleep(0.0001)
        assert len(entered) == 4
        fifth = await exchange(
            world, "/desktop/license/verify", "POST", headers=json_headers(world)
        )
        assert fifth[0] == 503 and fifth[1]["code"] == "local_busy"
        results = await asyncio.gather(*jobs)
        assert all(r[0] == 408 for r in results)
        good = await exchange(
            world, "/desktop/license/verify", "POST", b"{}", headers=json_headers(world)
        )
        assert good[0] == 202

    asyncio.run(scenario())
    assert done(world["client"]).phase == "activation_required"


def test_body_frame_budget_and_disconnect_do_not_start_client(world):
    async def scenario(kind):
        async def receive():
            if kind == "frames":
                return dict(type="http.request", body=b"", more_body=True)
            return dict(type="http.disconnect")

        return await exchange(
            world, "/desktop/license/verify", "POST", headers=json_headers(world), receive=receive
        )

    for kind in ("frames", "disconnect"):
        assert asyncio.run(scenario(kind))[0] == 422
    assert world["client"].view().phase == "new"


def test_lifespan_delegated_websocket_rejected(world):
    received = []

    async def inner(scope, receive, send):
        received.append(scope["type"])
        if scope["type"] == "lifespan":
            await send({"type": "lifespan.startup.complete"})

    wrapper = api().LicensedApplication(
        inner, world["client"], origin=LOCAL, session_token=world["token"]
    )

    async def scenario():
        sent = []

        async def receive():
            return dict(type="lifespan.startup")

        async def send(value):
            sent.append(value)

        await wrapper(dict(type="lifespan"), receive, send)
        await wrapper(dict(type="websocket"), receive, send)
        return sent

    assert asyncio.run(scenario()) == [
        {"type": "lifespan.startup.complete"},
        {"type": "websocket.close", "code": 1008},
    ]
    assert received == ["lifespan"]
    assert world["client"].view().phase == "new"


def test_unexpected_inner_exception_is_fixed(world):
    async def broken(scope, receive, send):
        raise ValueError("SYNTHETIC_PRIVATE")

    activate(world)
    world["app"] = api().LicensedApplication(
        broken, world["client"], origin=LOCAL, session_token=world["token"]
    )
    status, body, _, _ = call(world, D)
    assert status == 500 and body["code"] == "local_error"
    assert "SYNTHETIC_PRIVATE" not in json.dumps(body)
    assert world["client"].view().phase == "active"


def test_previously_admitted_work_can_finish_after_expiry(world):
    activate(world)
    permit = world["client"].require_active()

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def inner(scope, receive, send):
            calls.append(scope)
            entered.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        world["app"] = api().LicensedApplication(
            inner, world["client"], origin=LOCAL, session_token=world["token"]
        )
        first = asyncio.create_task(exchange(world, S + "/commands", "POST"))
        await entered.wait()
        world["clock"].value = permit.deadline_ns
        assert (await exchange(world, S + "/commands", "POST"))[0] == 403
        release.set()
        assert (await first)[0] == 200
        assert len(calls) == 1

    asyncio.run(scenario())
