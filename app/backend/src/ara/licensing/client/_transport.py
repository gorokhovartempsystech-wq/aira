"""One verified HTTPS request; no implicit proxies, redirects, retries or decompression."""

import ipaddress
import json
import re
from urllib.parse import urlsplit

import httpx

from .. import decode_grant, encode_request
from ._models import _ERRORS, ClientError, fail, require, safe

_REMOTE = {
    "validation_error",
    "invalid_record",
    "invalid_response",
    "invalid_license",
    "not_activated",
    "license_disabled",
    "device_mismatch",
    "license_expired",
    "clock_unavailable",
    "license_conflict",
    "license_schema_unavailable",
    "license_storage_unavailable",
    "license_storage_error",
    "license_busy",
    "https_required",
    "request_timeout",
    "request_too_large",
    "unsupported_media",
}


@safe("validation_error")
def checked_origin(origin):
    require(
        type(origin) is str and 1 <= len(origin) <= 2048 and origin.isascii(), "validation_error"
    )
    require(all(32 < ord(c) < 127 for c in origin) and "\\" not in origin, "validation_error")
    parsed = urlsplit(origin)
    require(
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and "?" not in origin
        and "#" not in origin,
        "validation_error",
    )
    host = parsed.hostname
    require(host is not None and not parsed.netloc.endswith(":"), "validation_error")
    require(parsed.port is None or 1 <= parsed.port <= 65535, "validation_error")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        require(
            len(host) <= 253
            and all(
                re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", part)
                for part in host.split(".")
            ),
            "validation_error",
        )
    return origin.rstrip("/")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "invalid_response")
        result[key] = value
    return result


@safe("invalid_response")
def _error(data, status):
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
    require(
        type(value) is dict
        and set(value) == {"code", "message"}
        and type(value["code"]) is str
        and type(value["message"]) is str,
        "invalid_response",
    )
    code = value["code"]
    require(code in _REMOTE and _ERRORS[code][0] == status, "invalid_response")
    fail(code)


class HttpsTransport:
    def __init__(self, origin):
        self._origin = checked_origin(origin)

    @safe("invalid_response")
    def execute(self, request, checkpoint):
        body = encode_request(request)
        checkpoint()
        try:
            with httpx.Client(
                verify=True,
                trust_env=False,
                follow_redirects=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
                timeout=httpx.Timeout(3.0, pool=0.5),
            ) as client:
                checkpoint()
                with client.stream(
                    "POST",
                    self._origin + "/license/v1/" + request.operation,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as reply:
                    checkpoint()
                    require(
                        reply.status_code == 200 or reply.status_code >= 400, "invalid_response"
                    )
                    media = reply.headers.get("content-type", "").lower().replace(" ", "")
                    require(
                        media in {"application/json", "application/json;charset=utf-8"},
                        "invalid_response",
                    )
                    require(
                        reply.headers.get("content-encoding", "identity").lower() == "identity",
                        "invalid_response",
                    )
                    length = reply.headers.get("content-length")
                    require(
                        length is None
                        or (re.fullmatch(r"[0-9]{1,5}", length) and int(length) <= 8192),
                        "invalid_response",
                    )
                    data = bytearray()
                    for chunk in reply.iter_raw(chunk_size=1024):
                        checkpoint()
                        require(len(data) + len(chunk) <= 8192, "invalid_response")
                        data.extend(chunk)
                    checkpoint()
                    require(length is None or len(data) == int(length), "invalid_response")
                    data = bytes(data)
                    if reply.status_code != 200:
                        _error(data, reply.status_code)
                    decode_grant(data)
                    return data
        except ClientError:
            raise
        except httpx.HTTPError:
            fail("network_unavailable")
