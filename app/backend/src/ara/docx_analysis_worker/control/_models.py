"""Small immutable snapshots; publication permits are process-local identities."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    run_id: UUID
    attempt_id: UUID
    worker_instance_id: UUID
    claim_fence: int


@dataclass(frozen=True, slots=True)
class Budget:
    deadline_ns: int
    lease_ns: int
    last_ns: int
    guard_ns: int


@dataclass(frozen=True, slots=True)
class ControlView:
    identity: AttemptIdentity
    phase: str
    stop_requested: bool
    stop_reason: str | None
    child_closed: bool
    deadline_ns: int
    lease_ns: int
    last_ns: int


class ControlError(Exception):
    def __init__(self, code="validation_error"):
        self.code = (
            code
            if code in ("validation_error", "invalid_permit", "conflicting_outcome")
            else "validation_error"
        )
        super().__init__(self.code)


class Uncopyable:
    __slots__ = ()

    def __copy__(self):
        raise TypeError("process-local authority")

    def __deepcopy__(self, memo):
        raise TypeError("process-local authority")

    def __reduce_ex__(self, protocol):
        raise TypeError("process-local authority")


_PERMIT_KEY = object()


class CommitPermit(Uncopyable):
    __slots__ = ()

    def __new__(cls, key=None):
        if key is not _PERMIT_KEY:
            raise TypeError("permits are issued by reserve")
        return super().__new__(cls)

    def __repr__(self):
        return "<CommitPermit>"


def new_permit():
    return CommitPermit(_PERMIT_KEY)
