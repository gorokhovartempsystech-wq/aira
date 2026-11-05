"""Detached licensing values and errors; no environment, clock or transport access."""

import re
from dataclasses import dataclass, field
from functools import wraps
from uuid import UUID

MAX_EPOCH_MS = 253402300799999
MAX_NS = 2**63 - 1
MAX_BODY = 8192
VERIFY_NS = 15_000_000_000

_ERRORS = {
    "validation_error": (422, "Invalid license input"),
    "invalid_record": (500, "Invalid stored license state"),
    "invalid_response": (502, "Invalid license server response"),
    "not_activated": (403, "License has not been activated"),
    "license_disabled": (403, "License is disabled"),
    "device_mismatch": (403, "License belongs to another device"),
    "license_expired": (403, "License has expired"),
    "clock_unavailable": (503, "Reliable license time is unavailable"),
    "verification_timeout": (503, "License verification timed out"),
}


class LicenseError(Exception):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERRORS else "validation_error"
        self.status, self.message = _ERRORS[self.code]
        super().__init__(self.message)


def fail(code):
    raise LicenseError(code) from None


def require(condition, code="validation_error"):
    if not condition:
        fail(code)


def safe(code):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except LicenseError:
                raise
            except Exception:
                fail(code)

        return run

    return decorate


def integer(value, maximum, code="validation_error", minimum=0):
    require(type(value) is int and minimum <= value <= maximum, code)
    return value


def identifier(value, code="validation_error"):
    require(type(value) is UUID and value.int != 0, code)
    return value


def uuid_text(value, code="validation_error"):
    require(type(value) is str and len(value) == 36, code)
    try:
        parsed = UUID(value)
    except ValueError:
        fail(code)
    require(str(parsed) == value, code)
    return identifier(parsed, code)


def hex_value(value, prefix="", code="validation_error"):
    require(type(value) is str and re.fullmatch(prefix + "[0-9a-f]{64}", value) is not None, code)
    return value


@dataclass(frozen=True)
class LicenseRecord:
    license_id: UUID
    duration_seconds: int
    enabled: bool = True
    device_id: str | None = None
    activated_at_ms: int | None = None
    expires_at_ms: int | None = None


@dataclass(frozen=True)
class StartRequest:
    operation: str
    device_id: str
    nonce: str
    license_key: str | None = field(default=None, repr=False)
    license_id: UUID | None = None


@dataclass(frozen=True)
class LaunchGrant:
    operation: str
    license_id: UUID
    device_id: str
    nonce: str
    activated_at_ms: int
    checked_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True)
class LaunchPermit:
    license_id: UUID
    device_id: str
    received_ns: int
    deadline_ns: int
    expires_at_ms: int
