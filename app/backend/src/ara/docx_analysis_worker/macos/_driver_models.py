"""Private immutable metadata; a transport candidate is not a model result."""

from dataclasses import dataclass


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
    fixture: bool = True
