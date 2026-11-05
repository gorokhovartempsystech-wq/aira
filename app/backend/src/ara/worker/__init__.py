"""Explicit local fixture worker; import performs no I/O and starts no work."""

from .execution import claim_next, complete_attempt, fail_attempt, run_once
from .fixture import fixture_result
from .types import Claim, WorkerSettings, WorkOutcome

__all__ = [
    "Claim",
    "WorkerSettings",
    "WorkOutcome",
    "claim_next",
    "complete_attempt",
    "fail_attempt",
    "fixture_result",
    "run_once",
]
