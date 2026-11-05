"""Pure one-device, fixed-entitlement rules and non-reversible lookup identifiers."""

import hashlib
import hmac
import re
from dataclasses import replace

from ._models import (
    MAX_EPOCH_MS,
    LaunchGrant,
    LicenseRecord,
    fail,
    hex_value,
    identifier,
    integer,
    require,
    safe,
    uuid_text,
)


@safe("validation_error")
def normalize_key(value):
    require(type(value) is str and len(value) <= 128 and value.isascii())
    normalized = value.strip(" \t\r\n").upper()
    require(re.fullmatch(r"AIRA(?:-[0-9A-F]{8}){4}", normalized) is not None)
    return normalized


def key_digest(key, pepper):
    require(type(pepper) is bytes and 32 <= len(pepper) <= 64)
    return hmac.new(pepper, normalize_key(key).encode("ascii"), hashlib.sha256).hexdigest()


def device_fingerprint(platform, hardware_uuid):
    require(type(platform) is str and platform in ("macos", "windows"))
    hardware = uuid_text(hardware_uuid)
    require(hardware.int != 2**128 - 1)
    data = b"aira-device-v1\0" + platform.encode("ascii") + b"\0" + hardware.bytes
    return "dv1-" + hashlib.sha256(data).hexdigest()


@safe("invalid_record")
def checked_record(record):
    code = "invalid_record"
    require(type(record) is LicenseRecord, code)
    identifier(record.license_id, code)
    integer(record.duration_seconds, MAX_EPOCH_MS // 1000, code, minimum=1)
    require(type(record.enabled) is bool, code)
    values = (record.device_id, record.activated_at_ms, record.expires_at_ms)
    if any(value is not None for value in values):
        require(all(value is not None for value in values), code)
        hex_value(record.device_id, "dv1-", code)
        integer(record.activated_at_ms, MAX_EPOCH_MS, code)
        integer(record.expires_at_ms, MAX_EPOCH_MS, code)
        require(
            record.expires_at_ms == record.activated_at_ms + record.duration_seconds * 1000, code
        )
    return replace(record)


def _evaluate(record, device_id, now_ms, *, activation):
    current = checked_record(record)
    hex_value(device_id, "dv1-")
    integer(now_ms, MAX_EPOCH_MS)
    if not current.enabled:
        fail("license_disabled")
    if current.device_id is None:
        if not activation:
            fail("not_activated")
        expires = now_ms + current.duration_seconds * 1000
        require(expires <= MAX_EPOCH_MS)
        return replace(current, device_id=device_id, activated_at_ms=now_ms, expires_at_ms=expires)
    if current.device_id != device_id:
        fail("device_mismatch")
    if now_ms < current.activated_at_ms:
        fail("clock_unavailable")
    if now_ms >= current.expires_at_ms:
        fail("license_expired")
    return current


def activate(record, *, device_id, now_ms):
    return _evaluate(record, device_id, now_ms, activation=True)


def check(record, *, device_id, now_ms):
    return _evaluate(record, device_id, now_ms, activation=False)


def make_grant(record, request, *, now_ms):
    from ._wire import checked_request

    request = checked_request(request)
    current = check(record, device_id=request.device_id, now_ms=now_ms)
    if request.operation == "check":
        require(current.license_id == request.license_id, "invalid_record")
    return LaunchGrant(
        request.operation,
        current.license_id,
        request.device_id,
        request.nonce,
        current.activated_at_ms,
        now_ms,
        current.expires_at_ms,
    )
