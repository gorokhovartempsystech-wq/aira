"""Detached fixture metadata. Neither a transport reply nor this DTO is SQL proof."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AttemptView:
    phase: str
    stage: str | None
    stop_requested: bool
    error_code: str | None
    exit_kind: str | None
    exit_code: int | None
    cleanup_confirmed: bool
    candidate_ready: bool
    permit_ready: bool
    resources_closed: bool
    fixture: bool = True


@dataclass(slots=True, repr=False)
class Command:
    lease: int
    old_lease: int
    cutoff: int
    token: object = field(default_factory=object)
    outcome: str = "pending"
    receipt: bool = False
