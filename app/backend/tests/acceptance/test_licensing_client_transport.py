"""HTTPS boundary with explicit mock sockets, not a production TLS deployment test."""

import json
from uuid import uuid4

import httpx
import pytest
from test_licensing_client_store import api, reject
from test_licensing_policy import BASE, DEVICE, NONCE, synthetic_key

from ara import licensing as core

_REAL_CLIENT = httpx.Client
ORIGIN = "https://license.example.invalid:443"


def request():
    return core.StartRequest("activate", DEVICE, NONCE, license_key=synthetic_key())


def response(req):
    return core.encode_grant(
        core.LaunchGrant(
            req.operation,
            uuid4(),
            req.device_id,
            req.nonce,
            BASE,
            BASE,
            BASE + 60000,
        )
    )


class Stream(httpx.SyncByteStream):
    def __init__(self, data):
        self.data, self.closed = data, False

    def __iter__(self):
        yield self.data[:7]
        yield self.data[7:]

    def close(self):
        self.closed = True


def mock_client(monkeypatch, *, data, status=200, headers=None, error=None):
    real, seen, stream = _REAL_CLIENT, [], Stream(data)

    def handler(req):
        seen.append(req)
        if error:
            raise error
        return httpx.Response(
            status, headers=headers or {"Content-Type": "application/json"}, stream=stream
        )

    def factory(**kwargs):
        assert kwargs["verify"] is True and kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        assert kwargs["limits"].max_connections == 1
        assert kwargs["limits"].max_keepalive_connections == 0
        assert kwargs["timeout"].connect <= 3 and kwargs["timeout"].read <= 3
        assert kwargs["timeout"].write <= 3 and kwargs["timeout"].pool <= 0.5
        return real(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "Client", factory)
    return seen, stream


@pytest.mark.parametrize(
    "origin",
    [
        "http://license.example",
        "https://user:pass@license.example",
        "https://license.example/path",
        "https://license.example?x=1",
        "https://license.example#x",
        "https://",
        "https://x:0",
        "https://x:99999",
        "https://x\\evil",
        "https://é.example",
        "https://x\n",
        None,
    ],
)
def test_invalid_origin(origin):
    reject("validation_error", lambda: api().HttpsTransport(origin))


def test_https_exact_request_bounded_raw_response_and_closed_transport(monkeypatch):
    req = request()
    data = response(req)
    seen, stream = mock_client(monkeypatch, data=data)
    checkpoints = []
    result = api().HttpsTransport(ORIGIN).execute(req, lambda: checkpoints.append(True))
    assert result == data and stream.closed and len(checkpoints) >= 3
    assert len(seen) == 1
    sent = seen[0]
    assert sent.method == "POST" and sent.url.path == "/license/v1/activate"
    assert sent.headers["accept-encoding"] == "identity"
    assert sent.content == core.encode_request(req)
    assert req.license_key not in str(sent.url)


@pytest.mark.parametrize(
    "status,headers,data",
    [
        (302, {"location": "https://other.invalid"}, b""),
        (200, {"content-type": "text/html"}, b"{}"),
        (200, {"content-type": "application/json", "content-encoding": "gzip"}, b"xx"),
        (200, {"content-type": "application/json", "content-length": "8193"}, b"{}"),
        (200, {"content-type": "application/json"}, b"x" * 8193),
        (200, {"content-type": "application/json"}, b"{}"),
        (
            500,
            {"content-type": "application/json"},
            b'{"code":"unknown","message":"SYNTHETIC_PRIVATE"}',
        ),
        (200, {"content-type": "application/json", "content-length": "-1"}, b"{}"),
    ],
)
def test_hostile_reply_rejected_and_closed(monkeypatch, status, headers, data):
    seen, stream = mock_client(monkeypatch, data=data, status=status, headers=headers)
    reject(
        "invalid_response", lambda: api().HttpsTransport(ORIGIN).execute(request(), lambda: None)
    )
    assert len(seen) == 1 and stream.closed


def test_known_server_error_sanitized_and_status_bound(monkeypatch):
    data = json.dumps({"code": "license_disabled", "message": "SYNTHETIC_PRIVATE"}).encode()
    mock_client(monkeypatch, data=data, status=403)
    reject(
        "license_disabled", lambda: api().HttpsTransport(ORIGIN).execute(request(), lambda: None)
    )
    mock_client(monkeypatch, data=data, status=503)
    reject(
        "invalid_response", lambda: api().HttpsTransport(ORIGIN).execute(request(), lambda: None)
    )


def test_network_error_never_leaks_request(monkeypatch):
    mock_client(monkeypatch, data=b"", error=httpx.ConnectError("SYNTHETIC_PRIVATE"))
    reject(
        "network_unavailable", lambda: api().HttpsTransport(ORIGIN).execute(request(), lambda: None)
    )


def test_checkpoint_failure_closes_response(monkeypatch):
    req = request()
    _, stream = mock_client(monkeypatch, data=response(req))
    calls = []

    def checkpoint():
        calls.append(True)
        if len(calls) > 2:
            raise api().ClientError("verification_timeout")

    reject("verification_timeout", lambda: api().HttpsTransport(ORIGIN).execute(req, checkpoint))
    assert stream.closed
