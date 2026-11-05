"""Worker tokens are locators; persisted bindings are always revalidated."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ara.docx_analysis.storage_codec import AttemptBundle, SourceBundle

from ._models import RunSummary


@dataclass(frozen=True, slots=True)
class RunState:
    summary: RunSummary
    attempt_id: UUID | None
    fence: int
    error_code: str | None
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkerUpdate:
    accepted: bool
    state: RunState
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class WorkerClaim:
    run_id: UUID
    document_id: UUID
    attempt_id: UUID
    worker_instance_id: UUID
    claim_fence: int
    source: SourceBundle = field(repr=False)
    attempt: AttemptBundle = field(repr=False)
    claimed_at: datetime
    deadline_at: datetime
    lease_expires_at: datetime
