"""Closed transport rejects redirects, malformed and cacheable key replies."""

import httpx
import pytest

from ara.model_protection.access_wire import AccessError
from ara.model_protection.client import AccessTransport, DeviceVault


@pytest.mark.parametrize(
    "status,headers,body",
    [
        (302, {"location": "https://other.example/"}, b"{}"),
        (200, {}, b"{}"),
        (200, {"cache-control": "public"}, b"{}"),
        (200, {"content-type": "text/html"}, b"{}"),
        (200, {"content-length": "99999"}, b"{}"),
        (200, {}, b'{"key":1,"key":2}'),
        (200, {}, b"x" * 8193),
        (403, {}, b'{"code":"other"}'),
    ],
)
def test_transport_fails_closed(monkeypatch, status, headers, body):
    defaults = {"content-type": "application/json", "cache-control": "no-store"}
    if headers == {} and body == b"{}" and status == 200:
        defaults.pop("cache-control")
    defaults.update(headers)
    original = httpx.Client

    def client(**kwargs):
        assert kwargs["verify"] is True
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, headers=defaults, content=body)
            ),
        )

    monkeypatch.setattr(httpx, "Client", client)
    with pytest.raises(AccessError, match="model_access_unavailable"):
        AccessTransport("https://license.example").execute("complete", {}, lambda: None)


def test_vault_never_uses_unselected_backend(monkeypatch):
    import ara.model_protection.client as module

    monkeypatch.setattr(module.sys, "platform", "linux")
    with pytest.raises(AccessError):
        DeviceVault("https://license.example").load("synthetic", "device")
