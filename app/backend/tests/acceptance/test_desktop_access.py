"""Independent local-capability and licensing admission policy."""

import asyncio
import copy
import importlib
import json
import os
import pickle
import secrets
from uuid import uuid4

import pytest
from test_licensing_client_runtime import Clock, Transport, done
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import DEVICE, synthetic_key

from ara.licensing.client import ActivationStore, ClientError, LicenseClient

LOCAL = "http://127.0.0.1:8767"
D = "/docx-documents/10000000-0000-0000-0000-000000000001"
S = D + "/editor-sessions/20000000-0000-0000-0000-000000000001"
R = D + "/analysis-runs/30000000-0000-0000-0000-000000000001"
Q = D + "/analysis-requests/40000000-0000-0000-0000-000000000001"
PRESERVE = [
    ("GET", "/docx-documents"),
    ("GET", D),
    ("GET", D + "/content"),
    ("GET", D + "/editor-recovery"),
    ("GET", S),
    ("GET", S + "/view"),
    *(
        ("POST", S + "/" + s)
        for s in ("checkpoint", "save", "reconcile", "close", "working-content", "saved-content")
    ),
    ("POST", D + "/editor-recovery/content"),
    ("GET", Q),
    ("POST", Q + "/stop"),
    ("GET", R),
    ("GET", R + "/result"),
    ("GET", R + "/review"),
    ("GET", D + "/analysis-result"),
    ("GET", D + "/analysis-review"),
    ("GET", D + "/analysis-preferences"),
]
PROTECTED = [
    *(
        ("POST", D + "/" + s)
        for s in (
            "create",
            "import",
            "editor-sessions",
            "editor-recovery/prepare-discard",
            "editor-recovery/discard",
            "analysis-runs",
            "analysis-preferences",
            "analysis-preferences/clear-hidden",
        )
    ),
    ("POST", S + "/commands"),
    ("POST", R + "/retry"),
    ("POST", R + "/findings/df-" + "a" * 64 + "/visibility"),
]


def api():
    return importlib.import_module("ara.desktop.access")


def reject(code, call):
    with pytest.raises((ClientError, api().AccessError)) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


class Inner:
    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"public"),
                    (b"access-control-allow-origin", b"*"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b'{"fixture":true}'})


@pytest.fixture
def world(tmp_path):
    clock, transport, inner, token = Clock(), Transport(), Inner(), secrets.token_bytes(32)
    client = LicenseClient(
        ORIGIN,
        ActivationStore(tmp_path / "activation"),
        clock=clock,
        transport=transport,
        device_provider=lambda: DEVICE,
    )
    wrapper = api().LicensedApplication(inner, client, origin=LOCAL, session_token=token)
    yield dict(
        clock=clock,
        transport=transport,
        inner=inner,
        token=token,
        client=client,
        app=wrapper,
        key=synthetic_key(),
    )
    transport.release.set()
    client.close()


def activate(w):
    w["client"].start(w["key"])
    assert done(w["client"]).phase == "active"


async def exchange(
    w, path="/desktop/license", method="GET", body=b"", *, headers=None, changes=None, receive=None
):
    pairs = [(b"host", b"127.0.0.1:8767"), (b"x-aira-session", w["token"].hex().encode())]
    if headers is not None:
        pairs = headers
    scope = dict(
        type="http",
        asgi={"version": "3.0"},
        http_version="1.1",
        method=method,
        scheme="http",
        path=path,
        raw_path=path.encode(),
        query_string=b"",
        root_path="",
        server=("127.0.0.1", 8767),
        client=("127.0.0.1", 50123),
        headers=pairs,
    )
    if changes:
        scope.update(changes)
    sent, consumed = [], []

    async def default_receive():
        consumed.append(True)
        return dict(type="http.request", body=body, more_body=False)

    async def send(message):
        sent.append(message)

    await w["app"](scope, receive or default_receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    data = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert dict(start["headers"])[b"cache-control"] == b"no-store"
    assert dict(start["headers"])[b"x-content-type-options"] == b"nosniff"
    assert dict(start["headers"])[b"referrer-policy"] == b"no-referrer"
    assert not any(k.lower().startswith(b"access-control-") for k, _ in start["headers"])
    return start["status"], json.loads(data), consumed, scope


def call(w, *args, **kwargs):
    return asyncio.run(exchange(w, *args, **kwargs))


def json_headers(w, *extra):
    return [
        (b"host", b"127.0.0.1:8767"),
        (b"x-aira-session", w["token"].hex().encode()),
        (b"content-type", b"application/json"),
        *extra,
    ]


@pytest.mark.parametrize("method,path", PRESERVE + PROTECTED)
def test_route_matrix_active_expired_and_closed(world, method, path):
    w = world
    assert call(w, path, method)[0] == 403
    assert not w["inner"].scopes
    activate(w)
    assert call(w, path, method)[0] == 200
    count = len(w["inner"].scopes)
    w["clock"].value = w["client"].require_active().deadline_ns
    expected = 200 if (method, path) in PRESERVE else 403
    assert call(w, path, method)[0] == expected
    assert len(w["inner"].scopes) == count + (expected == 200)
    w["client"].close()
    assert call(w, path, method)[0] == 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/documents"),
        ("GET", "/documents"),
        ("GET", "/me"),
        ("GET", "/health"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/workspace"),
        ("GET", "/workspace/assets/app.js"),
        ("GET", "/runs/" + str(uuid4())),
        ("PUT", D + "/content"),
        ("POST", D + "/text-edits"),
        ("POST", D + "/paragraph-commands"),
        ("PUT", D + "/draft"),
        ("GET", D + "/draft"),
        ("GET", D + "/view"),
        ("HEAD", D),
        ("OPTIONS", D),
        ("DELETE", D),
        ("POST", D + "/new-future-feature"),
        ("GET", D + "/"),
        ("GET", "/docx-documents/00000000-0000-0000-0000-000000000000"),
        ("GET", D.replace("10000000", "AAAAAAAA")),
    ],
)
def test_legacy_unknown_and_noncanonical_routes_never_forward(world, method, path):
    activate(world)
    assert call(world, path, method)[0] == 404
    assert world["inner"].scopes == []


@pytest.mark.parametrize(
    "kind",
    [
        "missing_token",
        "wrong_token",
        "upper_token",
        "duplicate_token",
        "cookie_token",
        "query_token",
        "host",
        "duplicate_host",
        "origin",
        "null_origin",
        "duplicate_origin",
        "cross-site",
        "same-site",
        "forwarded",
        "x-forwarded-host",
        "remote_client",
        "wrong_server",
        "https",
        "root",
        "control",
        "many_headers",
        "huge_header",
    ],
)
def test_untrusted_http_rejected_before_body_or_client(world, monkeypatch, kind):
    w = world
    headers = json_headers(w)
    changes = {}
    if kind == "missing_token":
        headers.pop(1)
    elif kind == "wrong_token":
        headers[1] = (b"x-aira-session", b"0" * 64)
    elif kind == "upper_token":
        headers[1] = (b"x-aira-session", b"A" * 64)
    elif kind == "duplicate_token":
        headers.append(headers[1])
    elif kind in {"cookie_token", "query_token"}:
        token = headers.pop(1)[1]
        if kind == "cookie_token":
            headers.append((b"cookie", b"x-aira-session=" + token))
        else:
            changes["query_string"] = b"token=" + token
    elif kind == "host":
        headers[0] = (b"host", b"evil.invalid:8767")
    elif kind == "duplicate_host":
        headers.append(headers[0])
    elif kind in {"origin", "null_origin", "duplicate_origin"}:
        value = (
            LOCAL.encode()
            if kind == "duplicate_origin"
            else b"null"
            if kind == "null_origin"
            else b"https://evil.invalid"
        )
        headers.append((b"origin", value))
        if kind == "duplicate_origin":
            headers.append((b"origin", value))
    elif kind in {"cross-site", "same-site"}:
        headers.append((b"sec-fetch-site", kind.encode()))
    elif kind in {"forwarded", "x-forwarded-host"}:
        headers.append((kind.encode(), b"SYNTHETIC_PRIVATE"))
    elif kind == "remote_client":
        changes["client"] = ("192.0.2.1", 50123)
    elif kind == "wrong_server":
        changes["server"] = ("0.0.0.0", 8767)
    elif kind == "https":
        changes["scheme"] = "https"
    elif kind == "root":
        changes["root_path"] = "/proxy"
    elif kind == "control":
        headers.append((b"x-test", b"a\x00b"))
    elif kind == "many_headers":
        headers.extend((b"x-test", b"value") for _ in range(65))
    else:
        headers.append((b"x-test", b"a" * 8192))

    def forbidden(*args, **kwargs):
        raise AssertionError("License state touched before local caller validation")

    for name in ("view", "start", "require_active"):
        monkeypatch.setattr(w["client"], name, forbidden)
    status, body, consumed, _ = call(w, headers=headers, changes=changes)
    assert status == 403 and body["code"] == "access_denied" and not consumed
    assert not w["inner"].scopes
    assert "SYNTHETIC_PRIVATE" not in json.dumps(body)
    assert w["token"].hex() not in json.dumps(body)


@pytest.mark.parametrize(
    "raw", [None, b"/docx-%64ocuments", b"/docx-documents%2f", b"//docx-documents"]
)
def test_raw_path_aliases_do_not_reach_inner(world, raw):
    activate(world)
    assert call(world, "/docx-documents", changes={"raw_path": raw})[0] == 404
    assert not world["inner"].scopes


def test_token_stripped_scope_not_mutated_and_same_origin_allowed(world):
    activate(world)
    headers = json_headers(world, (b"origin", LOCAL.encode()), (b"sec-fetch-site", b"same-origin"))
    status, _, _, original = call(world, D, headers=headers)
    assert status == 200
    assert b"x-aira-session" in dict(original["headers"])
    assert b"x-aira-session" not in dict(world["inner"].scopes[-1]["headers"])


def test_status_activation_verify_and_restart_need_actual_license(world):
    w = world
    status, body, _, _ = call(w)
    assert status == 200 and body == dict(
        schema_version="aira-desktop-license/1",
        phase="new",
        error_code=None,
        license_id=None,
        expires_at_ms=None,
        retry_available=True,
        preservation_available=False,
    )
    status, body, _, _ = call(
        w,
        "/desktop/license/activate",
        "POST",
        json.dumps({"license_key": w["key"]}).encode(),
        headers=json_headers(w),
    )
    assert status == 202 and body["phase"] == "checking"
    assert done(w["client"]).phase == "active"
    body = call(w)[1]
    assert body["phase"] == "active" and body["preservation_available"]
    assert body["expires_at_ms"].isdigit()
    assert w["key"] not in json.dumps(body) and DEVICE not in json.dumps(body)
    assert call(w, "/desktop/license/verify", "POST", b"{}", headers=json_headers(w))[0] == 202
    assert done(w["client"]).phase == "active"
    assert [r.operation for r in w["transport"].requests] == ["activate", "check"]
    w["clock"].value = w["client"].require_active().deadline_ns
    assert call(w)[1]["preservation_available"]
    fresh = api().LicensedApplication(
        w["inner"], w["client"], origin=LOCAL, session_token=w["token"]
    )
    original, w["app"] = w["app"], fresh
    assert call(w, D)[0] == 403
    w["app"] = original
    assert call(w, D)[0] == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8767",
        "http://127.0.0.1:80",
        "https://127.0.0.1:8767",
        LOCAL + "/",
        LOCAL + "?x",
        "http://127.0.0.1:08767",
        "http://0.0.0.0:8767",
    ],
)
def test_origin_constructor_strict(world, origin):
    reject(
        "validation_error",
        lambda: api().LicensedApplication(
            world["inner"], world["client"], origin=origin, session_token=world["token"]
        ),
    )


def test_runtime_cannot_cross_process_copy_pickle(world, monkeypatch):
    wrapper = world["app"]
    for op in (
        lambda: copy.copy(wrapper),
        lambda: copy.deepcopy(wrapper),
        lambda: pickle.dumps(wrapper),
    ):
        reject("invalid_handle", op)
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: -1)
        assert call(world)[0] == 500
    assert not world["inner"].scopes


def test_random_session_capability_not_echoed_or_created_by_constructor(world):
    first, second = api().new_session_token(), api().new_session_token()
    assert type(first) is bytes and len(first) == 32 and first != second
    assert world["token"].hex() not in repr(world["app"])
    for value in (None, "SYNTHETIC_PRIVATE", b"x" * 31, b"x" * 33):
        reject(
            "validation_error",
            lambda: api().LicensedApplication(
                world["inner"], world["client"], origin=LOCAL, session_token=value
            ),
        )
