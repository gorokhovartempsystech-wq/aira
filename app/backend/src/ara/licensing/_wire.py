"""Strict bounded JSON; transport authentication belongs to the HTTPS caller."""

import json
import re
from dataclasses import asdict, replace

from ._models import (
    MAX_BODY,
    MAX_EPOCH_MS,
    LaunchGrant,
    StartRequest,
    fail,
    hex_value,
    identifier,
    integer,
    require,
    safe,
    uuid_text,
)

REQUEST_VERSION = "aira-license-request/1"
GRANT_VERSION = "aira-license-grant/1"
TIMES = ("activated_at_ms", "checked_at_ms", "expires_at_ms")


@safe("validation_error")
def checked_request(request):
    from ._policy import normalize_key

    require(type(request) is StartRequest)
    require(type(request.operation) is str and request.operation in ("activate", "check"))
    hex_value(request.device_id, "dv1-")
    hex_value(request.nonce)
    if request.operation == "activate":
        require(request.license_id is None)
        return replace(request, license_key=normalize_key(request.license_key))
    require(request.license_key is None)
    identifier(request.license_id)
    return replace(request)


@safe("invalid_response")
def checked_grant(grant):
    code = "invalid_response"
    require(type(grant) is LaunchGrant, code)
    require(type(grant.operation) is str and grant.operation in ("activate", "check"), code)
    identifier(grant.license_id, code)
    hex_value(grant.device_id, "dv1-", code)
    hex_value(grant.nonce, code=code)
    for name in TIMES:
        integer(getattr(grant, name), MAX_EPOCH_MS, code)
    require(grant.activated_at_ms <= grant.checked_at_ms < grant.expires_at_ms, code)
    return replace(grant)


def _encoded(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _load(data, code):
    require(type(data) is bytes and 0 < len(data) <= MAX_BODY, code)

    def invalid(*args):
        fail(code)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, code)
            result[key] = value
        return result

    try:
        body = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=invalid,
            parse_float=invalid,
            parse_int=invalid,
        )
    except Exception:
        fail(code)
    require(type(body) is dict, code)
    return body


def _shape(body, fields, version, code):
    require(set(body) == {"schema_version", *fields} and body["schema_version"] == version, code)


def encode_request(request):
    checked = checked_request(request)
    body = dict(
        schema_version=REQUEST_VERSION,
        operation=checked.operation,
        device_id=checked.device_id,
        nonce=checked.nonce,
    )
    if checked.operation == "activate":
        body["license_key"] = checked.license_key
    else:
        body["license_id"] = str(checked.license_id)
    return _encoded(body)


@safe("validation_error")
def decode_request(data):
    body = _load(data, "validation_error")
    operation = body.get("operation")
    require(type(operation) is str and operation in ("activate", "check"))
    key = "license_key" if operation == "activate" else "license_id"
    _shape(body, ("operation", "device_id", "nonce", key), REQUEST_VERSION, "validation_error")
    value = body[key] if key == "license_key" else uuid_text(body[key])
    return checked_request(
        StartRequest(operation, body["device_id"], body["nonce"], **{key: value})
    )


def encode_grant(grant):
    checked = checked_grant(grant)
    body = asdict(checked) | {"schema_version": GRANT_VERSION}
    body["license_id"] = str(checked.license_id)
    for key in TIMES:
        body[key] = str(body[key])
    return _encoded(body)


@safe("invalid_response")
def decode_grant(data):
    code = "invalid_response"
    body = _load(data, code)
    fields = ("operation", "license_id", "device_id", "nonce", *TIMES)
    _shape(body, fields, GRANT_VERSION, code)
    values = {key: body[key] for key in fields}
    values["license_id"] = uuid_text(values["license_id"], code)
    for key in TIMES:
        value = values[key]
        require(type(value) is str and re.fullmatch(r"0|[1-9][0-9]{0,14}", value) is not None, code)
        values[key] = int(value)
    return checked_grant(LaunchGrant(**values))
