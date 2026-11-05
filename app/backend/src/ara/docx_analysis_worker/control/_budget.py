"""Conservative arithmetic over caller-provided continuous-clock nanoseconds."""

from uuid import UUID

from ._models import AttemptIdentity, Budget, ControlError

MAX = 2**63 - 1
DEADLINE = 300_000_000_000
LEASE = 15_000_000_000
GUARD = 50_000_000


def integer(value, maximum=MAX, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ControlError()
    return value


def total(started, remaining):
    return integer(started + remaining)


def identity_values(value):
    if type(value) is not AttemptIdentity:
        raise ControlError()
    values = tuple(
        getattr(value, n, None)
        for n in ("run_id", "attempt_id", "worker_instance_id", "claim_fence")
    )
    if not all(type(v) is UUID for v in values[:3]):
        raise ControlError()
    if type(values[3]) is not int or values[3] != 1:
        raise ControlError()
    return values


def validate_budget(value):
    if type(value) is not Budget:
        raise ControlError()
    deadline, lease, last, guard = (
        integer(getattr(value, n, None)) for n in ("deadline_ns", "lease_ns", "last_ns", "guard_ns")
    )
    if lease > deadline or deadline - last > DEADLINE or lease - last > LEASE or guard > GUARD:
        raise ControlError()
    return deadline, lease, last, guard


def make_budget(
    *, started_ns, received_ns, remaining_deadline_ns, remaining_lease_ns, guard_ns=GUARD
):
    s, r = integer(started_ns), integer(received_ns)
    d = integer(remaining_deadline_ns, DEADLINE, 1)
    lease_duration = integer(remaining_lease_ns, LEASE, 1)
    g = integer(guard_ns, GUARD)
    if r < s or lease_duration > d:
        raise ControlError()
    deadline = max(s, total(s, d) - g)
    lease = min(deadline, max(s, total(s, lease_duration) - g))
    return Budget(deadline, lease, r, g)
