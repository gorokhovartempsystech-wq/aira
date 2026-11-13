"""Public detached client values and fixed, non-reflecting errors."""

import re
from dataclasses import dataclass
from functools import wraps
from uuid import UUID

from .. import LicenseError

_ERRORS = {
    "model_access_unavailable": (503, "Protected model access could not be confirmed"),
    "validation_error": (422, "Invalid license input"),
    "invalid_response": (502, "Invalid license server response"),
    "invalid_record": (500, "Invalid stored license state"),
    "invalid_license": (403, "License was not found"),
    "not_activated": (403, "License has not been activated"),
    "license_disabled": (403, "License is disabled"),
    "device_mismatch": (403, "License belongs to another device"),
    "license_expired": (403, "License has expired"),
    "license_conflict": (409, "License conflicts with stored state"),
    "clock_unavailable": (503, "Reliable license time is unavailable"),
    "verification_timeout": (503, "License verification timed out"),
    "license_schema_unavailable": (503, "License service is unavailable"),
    "license_storage_unavailable": (503, "License service is unavailable"),
    "license_storage_error": (500, "License service is unavailable"),
    "license_busy": (503, "License service is busy"),
    "https_required": (400, "Secure license connection is required"),
    "request_timeout": (408, "License request timed out"),
    "request_too_large": (413, "License request is too large"),
    "unsupported_media": (415, "Unsupported license request"),
    "network_unavailable": (503, "Secure license server connection is unavailable"),
    "device_unavailable": (503, "Stable device identity is unavailable"),
    "activation_store_error": (503, "Local activation could not be read or saved"),
    "access_denied": (403, "Online license verification is required"),
    "client_busy": (409, "License verification is still running"),
    "client_closed": (409, "License client is closed"),
    "invalid_handle": (500, "License client belongs to another runtime"),
    "client_error": (500, "License verification failed"),
}


class ClientError(Exception):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _ERRORS else "client_error"
        self.status, self.message = _ERRORS[self.code]
        super().__init__(self.message)


def fail(code):
    raise ClientError(code) from None


def require(condition, code):
    if not condition:
        fail(code)


def safe(code):
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except ClientError:
                raise
            except LicenseError as exc:
                fail(exc.code)
            except Exception:
                fail(code)

        return call

    return decorate


@dataclass(frozen=True)
class ActivationIdentity:
    license_id: UUID
    device_id: str


def checked_identity(value, code="validation_error"):
    try:
        require(type(value) is ActivationIdentity, code)
        require(type(value.license_id) is UUID and value.license_id.int != 0, code)
        require(
            type(value.device_id) is str and re.fullmatch(r"dv1-[0-9a-f]{64}", value.device_id),
            code,
        )
        return ActivationIdentity(value.license_id, value.device_id)
    except ClientError:
        raise
    except Exception:
        fail(code)


@dataclass(frozen=True)
class Snapshot:
    phase: str
    error_code: str | None = None
    license_id: UUID | None = None
    expires_at_ms: int | None = None
    retry_available: bool = True
