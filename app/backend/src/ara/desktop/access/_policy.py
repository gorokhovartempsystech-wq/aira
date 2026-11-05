"""Exact desktop routes, deliberately excluding the historical development API."""

import hmac
import re
from uuid import UUID

from ._models import fail, require

_UUID = r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
_D = r"/docx-documents/" + _UUID
_S = _D + r"/editor-sessions/" + _UUID
_R = _D + r"/analysis-runs/" + _UUID
_Q = _D + r"/analysis-requests/" + _UUID
_RULES = [
    ("GET", r"/docx-documents", "preserve"),
    ("GET", _D, "preserve"),
    (
        "GET",
        _D + r"/(?:content|editor-recovery|analysis-result|analysis-review|analysis-preferences)",
        "preserve",
    ),
    ("GET", _S + r"(?:/view)?", "preserve"),
    (
        "POST",
        _S + r"/(?:checkpoint|save|reconcile|close|working-content|saved-content)",
        "preserve",
    ),
    ("POST", _D + r"/editor-recovery/content", "preserve"),
    ("GET", _Q, "preserve"),
    ("POST", _Q + r"/stop", "preserve"),
    ("GET", _R + r"(?:/result|/review)?", "preserve"),
    (
        "POST",
        _D + r"/(?:create|import|editor-sessions|analysis-runs|analysis-preferences)",
        "active",
    ),
    ("POST", _D + r"/editor-recovery/(?:prepare-discard|discard)", "active"),
    ("POST", _D + r"/analysis-preferences/clear-hidden", "active"),
    ("POST", _S + r"/commands", "active"),
    ("POST", _R + r"/retry", "active"),
    ("POST", _R + r"/findings/df-[0-9a-f]{64}/visibility", "active"),
]
_RULES = tuple((method, re.compile(path), kind) for method, path, kind in _RULES)
_HEADERS = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def checked_origin(origin):
    require(type(origin) is str, "validation_error")
    match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{3,4})", origin)
    require(match is not None and 1024 <= int(match[1]) <= 65535, "validation_error")
    return int(match[1])


def local_request(scope, *, origin, port, token):
    code = "access_denied"
    require(scope.get("scheme") == "http" and not scope.get("root_path", ""), code)
    require(scope.get("server") in (("127.0.0.1", port), ["127.0.0.1", port]), code)
    peer = scope.get("client")
    require(
        isinstance(peer, (list, tuple))
        and len(peer) == 2
        and peer[0] == "127.0.0.1"
        and type(peer[1]) is int
        and 0 <= peer[1] <= 65535,
        code,
    )
    pairs = scope.get("headers")
    require(type(pairs) in (list, tuple) and len(pairs) <= 64, code)
    headers, size = {}, 0
    for pair in pairs:
        require(type(pair) in (list, tuple) and len(pair) == 2, code)
        name, value = pair
        require(type(name) is bytes and type(value) is bytes, code)
        size += len(name) + len(value)
        require(size <= 8192 and _HEADERS.fullmatch(name) is not None, code)
        require(not any(c in value for c in (b"\r", b"\n", b"\x00")), code)
        name = name.lower()
        require(name != b"forwarded" and not name.startswith(b"x-forwarded-"), code)
        headers.setdefault(name, []).append(value)
    require(headers.get(b"host") == [f"127.0.0.1:{port}".encode()], code)
    require(headers.get(b"origin", []) in ([], [origin.encode()]), code)
    require(headers.get(b"sec-fetch-site", []) in ([], [b"same-origin"], [b"none"]), code)
    values = headers.get(b"x-aira-session", [])
    require(len(values) == 1 and re.fullmatch(rb"[0-9a-f]{64}", values[0]) is not None, code)
    require(hmac.compare_digest(values[0], token.hex().encode()), code)
    return headers


def classify(scope):
    code = "route_unavailable"
    path, raw, method = scope.get("path"), scope.get("raw_path"), scope.get("method")
    require(type(path) is str and path.isascii() and len(path) <= 2048, code)
    require(type(raw) is bytes and raw == path.encode("ascii"), code)
    if (method, path) == ("GET", "/desktop/license"):
        return "status"
    if (method, path) in (
        ("POST", "/desktop/license/activate"),
        ("POST", "/desktop/license/verify"),
    ):
        return path.rsplit("/", 1)[1]
    for verb, pattern, kind in _RULES:
        if verb == method:
            match = pattern.fullmatch(path)
            if match is not None and all(UUID(value).int != 0 for value in match.groups()):
                return kind
    fail(code)
