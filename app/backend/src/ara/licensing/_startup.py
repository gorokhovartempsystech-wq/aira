"""Conservative admission for one authenticated online reply, never an offline token."""

from ._models import (
    MAX_EPOCH_MS,
    MAX_NS,
    VERIFY_NS,
    LaunchPermit,
    fail,
    hex_value,
    identifier,
    integer,
    require,
    safe,
)
from ._wire import checked_request, decode_grant


def authorize_start(request, grant_data, *, started_ns, received_ns):
    request = checked_request(request)
    integer(started_ns, MAX_NS)
    integer(received_ns, MAX_NS)
    if received_ns < started_ns:
        fail("clock_unavailable")
    if received_ns - started_ns > VERIFY_NS:
        fail("verification_timeout")
    grant = decode_grant(grant_data)
    require(
        (grant.operation, grant.device_id, grant.nonce)
        == (request.operation, request.device_id, request.nonce)
        and (request.operation != "check" or request.license_id == grant.license_id),
        "invalid_response",
    )
    deadline = started_ns + (grant.expires_at_ms - grant.checked_at_ms - 1) * 1_000_000
    if received_ns >= deadline:
        fail("license_expired")
    return LaunchPermit(
        grant.license_id, grant.device_id, received_ns, deadline, grant.expires_at_ms
    )


@safe("invalid_record")
def _permit(permit):
    code = "invalid_record"
    require(type(permit) is LaunchPermit, code)
    identifier(permit.license_id, code)
    hex_value(permit.device_id, "dv1-", code)
    integer(permit.received_ns, MAX_NS, code)
    integer(permit.deadline_ns, MAX_NS + MAX_EPOCH_MS * 1_000_000, code, minimum=1)
    integer(permit.expires_at_ms, MAX_EPOCH_MS, code, minimum=1)
    require(permit.deadline_ns > permit.received_ns, code)


def require_access(permit, *, now_ns):
    _permit(permit)
    integer(now_ns, MAX_NS)
    if now_ns < permit.received_ns:
        fail("clock_unavailable")
    if now_ns >= permit.deadline_ns:
        fail("license_expired")
