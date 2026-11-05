"""Independent D04-01 rules: no entitlement renewal or cached-start authority."""

import importlib
import json
import secrets
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from hmac import new as hmac_new
from pathlib import Path
from uuid import UUID, uuid4

import pytest

MAX_TIME = 253402300799999
BASE = 1_800_000_000_000
DEVICE = "dv1-" + "a" * 64
OTHER = "dv1-" + "b" * 64
NONCE = "c" * 64


def api():
    return importlib.import_module("ara.licensing")


def canonical(body):
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def synthetic_key():
    raw = secrets.token_hex(16).upper()
    return "AIRA-" + "-".join(raw[i : i + 8] for i in range(0, 32, 8))


def reject(code, call):
    with pytest.raises(api().LicenseError) as caught:
        call()
    assert caught.value.code == code
    assert type(caught.value.status) is int and 400 <= caught.value.status <= 599
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
    assert "SYNTHETIC_PRIVATE" not in repr(caught.value)


@pytest.fixture
def world():
    a = api()
    key = synthetic_key()
    record = a.LicenseRecord(uuid4(), 60)
    request = a.StartRequest("activate", DEVICE, NONCE, license_key=key)
    active = a.activate(record, device_id=DEVICE, now_ms=BASE)
    grant = a.make_grant(active, request, now_ms=BASE + 1000)
    return a, record, request, active, grant


@pytest.mark.parametrize("seconds", [1, 60, 86400, 100 * 365 * 86400])
def test_duration_from_first_activation_and_repeat_never_renews(seconds):
    a = api()
    record = a.LicenseRecord(uuid4(), seconds)
    first = a.activate(record, device_id=DEVICE, now_ms=BASE)
    assert record.device_id is None and record.activated_at_ms is None
    assert first.activated_at_ms == BASE and first.expires_at_ms == BASE + seconds * 1000
    for now in (BASE, first.expires_at_ms - 1):
        again = a.activate(first, device_id=DEVICE, now_ms=now)
        assert again == first and again is not first
        assert a.check(first, device_id=DEVICE, now_ms=now) == first
    for operation in (a.activate, a.check):
        reject(
            "license_expired",
            lambda: operation(first, device_id=DEVICE, now_ms=first.expires_at_ms),
        )


def test_activation_and_device_boundaries(world):
    a, record, _, active, _ = world
    reject("not_activated", lambda: a.check(record, device_id=DEVICE, now_ms=BASE))
    for operation in (a.activate, a.check):
        reject("device_mismatch", lambda: operation(active, device_id=OTHER, now_ms=BASE))
        reject(
            "license_disabled",
            lambda: operation(replace(active, enabled=False), device_id=DEVICE, now_ms=BASE),
        )
        reject("clock_unavailable", lambda: operation(active, device_id=DEVICE, now_ms=BASE - 1))
    assert active.activated_at_ms == BASE and active.expires_at_ms == BASE + 60000


@pytest.mark.parametrize(
    "changes",
    [
        {"license_id": UUID(int=0)},
        {"duration_seconds": True},
        {"duration_seconds": 0},
        {"duration_seconds": MAX_TIME},
        {"enabled": 1},
        {"device_id": DEVICE},
        {"activated_at_ms": BASE},
        {"expires_at_ms": BASE + 60000},
        {"device_id": DEVICE, "activated_at_ms": BASE, "expires_at_ms": BASE + 1},
        {
            "device_id": DEVICE,
            "activated_at_ms": MAX_TIME - 1000,
            "expires_at_ms": MAX_TIME + 59000,
        },
    ],
)
def test_corrupt_records_are_not_reactivated_or_repaired(world, changes):
    a, record, _, _, _ = world
    bad = replace(record, **changes)
    reject("invalid_record", lambda: a.activate(bad, device_id=DEVICE, now_ms=BASE))
    reject("invalid_record", lambda: a.check(bad, device_id=DEVICE, now_ms=BASE))


@pytest.mark.parametrize("now", [True, 1.5, -1, MAX_TIME + 1, "SYNTHETIC_PRIVATE"])
def test_invalid_clock_input_fails_safely(world, now):
    a, record, _, _, _ = world
    reject("validation_error", lambda: a.activate(record, device_id=DEVICE, now_ms=now))


def test_mutated_dto_overflow_and_frozen_result(world):
    a, record, _, active, _ = world
    object.__setattr__(record, "enabled", "SYNTHETIC_PRIVATE")
    reject("invalid_record", lambda: a.activate(record, device_id=DEVICE, now_ms=BASE))
    reject(
        "validation_error",
        lambda: a.activate(a.LicenseRecord(uuid4(), 2), device_id=DEVICE, now_ms=MAX_TIME - 1000),
    )
    with pytest.raises(FrozenInstanceError):
        active.expires_at_ms += 1


def test_key_normalization_and_independent_digest_oracle():
    a, key, pepper = api(), synthetic_key(), secrets.token_bytes(32)
    assert a.normalize_key(" \t" + key.lower() + "\r\n") == key
    assert (
        a.key_digest(key.lower(), pepper)
        == hmac_new(pepper, key.encode("ascii"), sha256).hexdigest()
    )
    assert a.key_digest(key, pepper) != a.key_digest(key, secrets.token_bytes(32))
    for value in (None, "SYNTHETIC_PRIVATE", key + "x", key.replace("A", "А", 1), " " * 129):
        reject("validation_error", lambda: a.normalize_key(value))
    for value in (b"x" * 31, b"x" * 65, "SYNTHETIC_PRIVATE", bytearray(32)):
        reject("validation_error", lambda: a.key_digest(key, value))


def test_device_domain_and_platform_are_distinct():
    a, hardware = api(), str(uuid4())
    for platform in ("macos", "windows"):
        expected = (
            "dv1-"
            + sha256(
                b"aira-device-v1\0" + platform.encode() + b"\0" + UUID(hardware).bytes
            ).hexdigest()
        )
        assert a.device_fingerprint(platform, hardware) == expected
    assert a.device_fingerprint("macos", hardware) != a.device_fingerprint("windows", hardware)
    for platform, value in (
        ("linux", hardware),
        ("macos", str(UUID(int=0))),
        ("windows", str(UUID(int=2**128 - 1))),
        ("macos", hardware.upper()),
        ("macos", "SYNTHETIC_PRIVATE"),
    ):
        reject("validation_error", lambda: a.device_fingerprint(platform, value))


def test_exact_wire_and_public_grant_without_key(world):
    a, _, request, active, grant = world
    body = dict(
        schema_version="aira-license-request/1",
        operation="activate",
        device_id=DEVICE,
        nonce=NONCE,
        license_key=request.license_key,
    )
    assert a.encode_request(request) == canonical(body)
    assert a.decode_request(json.dumps(body, indent=2).encode()) == request
    assert request.license_key not in repr(request)
    check = a.StartRequest("check", DEVICE, "d" * 64, license_id=active.license_id)
    assert a.decode_request(a.encode_request(check)) == check
    result = dict(
        schema_version="aira-license-grant/1",
        operation="activate",
        license_id=str(active.license_id),
        device_id=DEVICE,
        nonce=NONCE,
        activated_at_ms=str(BASE),
        checked_at_ms=str(BASE + 1000),
        expires_at_ms=str(BASE + 60000),
    )
    assert a.encode_grant(grant) == canonical(result)
    assert a.decode_grant(canonical(result)) == grant
    assert request.license_key.encode() not in a.encode_grant(grant)
    assert "license_key" not in result


@pytest.mark.parametrize("which", ["request", "grant"])
@pytest.mark.parametrize(
    "fault",
    ["duplicate", "extra", "missing", "utf8", "deep", "large", "nan", "wrong_version", "array"],
)
def test_wire_rejects_malformed_without_echo(world, which, fault):
    a, _, request, _, grant = world
    encode, decode = getattr(a, "encode_" + which), getattr(a, "decode_" + which)
    raw = encode(request if which == "request" else grant)
    body = json.loads(raw)
    if fault == "duplicate":
        raw = raw[:-1] + b',"nonce":"SYNTHETIC_PRIVATE"}'
    elif fault == "extra":
        raw = canonical(body | {"SYNTHETIC_PRIVATE": "hidden"})
    elif fault == "missing":
        del body["nonce"]
        raw = canonical(body)
    elif fault == "utf8":
        raw = b"\xff"
    elif fault == "deep":
        raw = b"[" * 2000 + b"0" + b"]" * 2000
    elif fault == "large":
        raw = b" " * 8193
    elif fault == "nan":
        raw = raw[:-1] + b',"extra":NaN}'
    elif fault == "wrong_version":
        raw = canonical(body | {"schema_version": "SYNTHETIC_PRIVATE"})
    else:
        raw = b"[]"
    reject("validation_error" if which == "request" else "invalid_response", lambda: decode(raw))


@pytest.mark.parametrize(
    "field,value",
    [
        ("activated_at_ms", True),
        ("checked_at_ms", BASE),
        ("expires_at_ms", "01"),
        ("nonce", "D" * 64),
        ("license_id", "00000000-0000-0000-0000-000000000000"),
    ],
)
def test_grant_strict_scalar_types(world, field, value):
    a, _, _, _, grant = world
    body = json.loads(a.encode_grant(grant)) | {field: value}
    reject("invalid_response", lambda: a.decode_grant(canonical(body)))


def test_request_shape_mutation_and_check_identity(world):
    a, _, request, active, grant = world
    for changed in (
        replace(request, license_id=uuid4()),
        replace(request, operation="check"),
        replace(request, nonce="SYNTHETIC_PRIVATE"),
    ):
        reject("validation_error", lambda: a.encode_request(changed))
    check = a.StartRequest("check", DEVICE, NONCE, license_id=uuid4())
    reject("invalid_record", lambda: a.make_grant(active, check, now_ms=BASE))
    object.__setattr__(grant, "expires_at_ms", True)
    reject("invalid_response", lambda: a.encode_grant(grant))


def test_permit_charges_network_time_and_rounding_without_wall_clock(world):
    a, _, request, active, grant = world
    started, received = 10_000_000_000, 12_000_000_000
    permit = a.authorize_start(
        request, a.encode_grant(grant), started_ns=started, received_ns=received
    )
    expected = started + (active.expires_at_ms - grant.checked_at_ms - 1) * 1_000_000
    assert permit.deadline_ns == expected and permit.received_ns == received
    assert permit.license_id == active.license_id and permit.device_id == DEVICE
    assert request.license_key not in repr(permit) and NONCE not in repr(permit)
    assert a.require_access(permit, now_ns=expected - 1) is None
    reject("license_expired", lambda: a.require_access(permit, now_ns=expected))
    reject("clock_unavailable", lambda: a.require_access(permit, now_ns=received - 1))
    with pytest.raises(FrozenInstanceError):
        permit.deadline_ns += 1
    object.__setattr__(permit, "deadline_ns", True)
    reject("invalid_record", lambda: a.require_access(permit, now_ns=received))


@pytest.mark.parametrize(
    "change", [{"nonce": "d" * 64}, {"device_id": OTHER}, {"operation": "check"}]
)
def test_start_response_bound_to_current_attempt(world, change):
    a, _, request, _, grant = world
    raw = a.encode_grant(replace(grant, **change))
    reject("invalid_response", lambda: a.authorize_start(request, raw, started_ns=0, received_ns=0))


def test_check_response_requires_same_license_and_timing(world):
    a, _, _, active, _ = world
    request = a.StartRequest("check", DEVICE, NONCE, license_id=active.license_id)
    grant = a.make_grant(active, request, now_ms=BASE)
    raw = a.encode_grant(grant)
    assert a.authorize_start(request, raw, started_ns=0, received_ns=15_000_000_000)
    reject(
        "verification_timeout",
        lambda: a.authorize_start(request, raw, started_ns=0, received_ns=15_000_000_001),
    )
    reject(
        "clock_unavailable", lambda: a.authorize_start(request, raw, started_ns=2, received_ns=1)
    )
    reject(
        "validation_error", lambda: a.authorize_start(request, raw, started_ns=True, received_ns=1)
    )
    other = a.encode_grant(replace(grant, license_id=uuid4()))
    reject(
        "invalid_response", lambda: a.authorize_start(request, other, started_ns=0, received_ns=1)
    )
    short = a.encode_grant(replace(grant, expires_at_ms=BASE + 1))
    reject(
        "license_expired", lambda: a.authorize_start(request, short, started_ns=0, received_ns=0)
    )
    short = a.encode_grant(replace(grant, expires_at_ms=BASE + 2001))
    reject(
        "license_expired",
        lambda: a.authorize_start(request, short, started_ns=0, received_ns=2_000_000_000),
    )


def test_import_and_operations_have_no_implicit_io_or_clock(world, monkeypatch):
    a, record, request, _, grant = world

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected implicit operation")

    import builtins
    import os
    import socket
    import time

    with monkeypatch.context() as patch:
        for module, name in (
            (builtins, "open"),
            (os, "getenv"),
            (socket, "socket"),
            (subprocess, "Popen"),
            (time, "time"),
            (time, "monotonic"),
            (Path, "home"),
        ):
            patch.setattr(module, name, forbidden)
        a.activate(record, device_id=DEVICE, now_ms=BASE)
        a.decode_request(a.encode_request(request))
        a.authorize_start(request, a.encode_grant(grant), started_ns=0, received_ns=0)
    script = """
import sys, socket, subprocess, os, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
def forbidden(*args, **kwargs): raise AssertionError("implicit initialization")
socket.socket = subprocess.Popen = os.getenv = time.time = time.monotonic = Path.home = forbidden
import ara.licensing
print("inert")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(Path.cwd() / "src")],
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "inert\n"
