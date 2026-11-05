"""Small strict local license requests, bounded independently of upstream verification."""

import json
import re

import anyio

from ._models import AccessError, fail, require

BODY_TIMEOUT = 3.0


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "validation_error")
        result[key] = value
    return result


def _constant(value):
    fail("validation_error")


def decode(data, operation):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        fields = {"license_key"} if operation == "activate" else set()
        require(type(value) is dict and set(value) == fields, "validation_error")
        if fields:
            require(type(value["license_key"]) is str, "validation_error")
        return value
    except AccessError:
        raise
    except Exception:
        fail("validation_error")


async def read_body(receive, headers, *, post):
    lengths = headers.get(b"content-length", [])
    types = headers.get(b"content-type", [])
    encodings = headers.get(b"content-encoding", [])
    require(len(lengths) <= 1 and len(types) <= 1 and len(encodings) <= 1, "validation_error")
    require(b"transfer-encoding" not in headers, "validation_error")
    require(not encodings or encodings[0].lower() == b"identity", "unsupported_media")
    if post:
        require(
            len(types) == 1
            and types[0].lower().replace(b" ", b"")
            in (b"application/json", b"application/json;charset=utf-8"),
            "unsupported_media",
        )
    length = None
    if lengths:
        require(re.fullmatch(rb"[0-9]{1,20}", lengths[0]) is not None, "validation_error")
        length = int(lengths[0])
        require(length <= 1024, "request_too_large")
        require(post or length == 0, "validation_error")
    result = bytearray()
    try:
        with anyio.fail_after(BODY_TIMEOUT):
            for _ in range(32):
                message = await receive()
                require(
                    type(message) is dict and message.get("type") == "http.request",
                    "validation_error",
                )
                chunk, more = message.get("body", b""), message.get("more_body", False)
                require(type(chunk) is bytes and type(more) is bool, "validation_error")
                require(post or not chunk, "validation_error")
                require(len(result) + len(chunk) <= 1024, "request_too_large")
                result.extend(chunk)
                if not more:
                    require(length is None or length == len(result), "validation_error")
                    return bytes(result)
    except TimeoutError:
        fail("request_timeout")
    fail("validation_error")


def snapshot(value, preservation):
    return dict(
        schema_version="aira-desktop-license/1",
        phase=value.phase,
        error_code=value.error_code,
        license_id=str(value.license_id) if value.license_id else None,
        expires_at_ms=str(value.expires_at_ms) if value.expires_at_ms is not None else None,
        retry_available=value.retry_available,
        preservation_available=preservation and value.phase != "closed",
    )


async def license_request(application, kind, scope, receive, headers):
    require(not scope.get("query_string", b""), "validation_error")
    require(application._body_slots.acquire(blocking=False), "local_busy")
    try:
        data = await read_body(receive, headers, post=kind != "status")
        if kind == "status":
            value = application._observe()
            return 200, snapshot(value, application._ever_verified)
        body = decode(data, kind)
        value = application._license.start(body.get("license_key"))
        return 202, snapshot(value, application._ever_verified)
    finally:
        application._body_slots.release()


def response_headers(headers):
    replaced = {b"cache-control", b"x-content-type-options", b"referrer-policy"}
    result = [
        (name, value)
        for name, value in headers
        if name.lower() not in replaced and not name.lower().startswith(b"access-control-")
    ]
    return result + [
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
    ]


async def reply(send, status, body):
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": response_headers(
                [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(data)).encode()),
                ]
            ),
        }
    )
    await send({"type": "http.response.body", "body": data})
