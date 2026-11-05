"""One cell per lane; auxiliary wall time only bounds waits, never grants authority."""

from dataclasses import dataclass
from time import monotonic_ns

WAIT_NS = 50_000_000


@dataclass(slots=True)
class LeaseCell:
    ticket: object
    started: int
    received: int
    duration: int
    decision: object = None


@dataclass(slots=True)
class ReserveCell:
    state: str = "requested"
    token: object = None


@dataclass(slots=True)
class SettleCell:
    token: object
    outcome: str
    done: bool = False
    result: object = None
    error: str | None = None


class WaitBudget:
    def __init__(self, now):
        self.start = now
        self.wall = monotonic_ns() + WAIT_NS

    def remaining(self, now):
        # Regression is separately latched as a clock fault by the caller.
        return min(self.wall - monotonic_ns(), self.start + WAIT_NS - now)
