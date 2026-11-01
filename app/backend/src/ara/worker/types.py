"""Detached worker values. Construction never performs I/O."""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from ara.analysis_contract import AnalysisRequest


@dataclass(frozen=True)
class WorkerSettings:
    lease_seconds: float = 30
    max_attempts: int = 3
    run_timeout_seconds: float = 900
    retry_delay_seconds: float = 1

    def __post_init__(self):
        valid = type(self.max_attempts) is int and 1 <= self.max_attempts <= 10
        for value, maximum, allow_zero in (
            (self.lease_seconds, 300, False),
            (self.run_timeout_seconds, 86400, False),
            (self.retry_delay_seconds, 300, True),
        ):
            valid = valid and (
                type(value) in (int, float)
                and 0 <= value <= maximum
                and (allow_zero or value > 0)
                and math.isfinite(value)
            )
        if not valid:
            raise ValueError("Invalid worker settings")


@dataclass(frozen=True)
class Claim:
    run_id: UUID
    attempt_id: UUID
    attempt_number: int
    request: AnalysisRequest
    has_import_omissions: bool
    lease_expires_at: datetime
    deadline_at: datetime


@dataclass(frozen=True)
class WorkOutcome:
    outcome: Literal["idle", "succeeded", "retry_scheduled", "failed", "stale"]
    run_id: UUID | None
