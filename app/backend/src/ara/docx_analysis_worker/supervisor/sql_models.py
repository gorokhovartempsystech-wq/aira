"""SQL metadata only; these values do not attest OS ownership or physical exit."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ara.docx_analysis_runs._lifecycle_models import RunState, WorkerClaim


class SupervisorStorageError(Exception):
    def __init__(self, code="storage_error"):
        self.code = (
            code
            if code
            in {
                "validation_error",
                "storage_conflict",
                "recovery_required",
                "storage_unavailable",
                "storage_error",
                "queue_overflow",
            }
            else "storage_error"
        )
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class OwnerBinding:
    installation_id: UUID
    owner_epoch: UUID


@dataclass(frozen=True, slots=True)
class LaunchBinding:
    owner: OwnerBinding
    launch_id: UUID
    document_id: UUID
    run_id: UUID
    attempt_id: UUID
    worker_instance_id: UUID
    claim_fence: int = 1


@dataclass(frozen=True, slots=True)
class FenceView:
    revision: int
    phase: str
    installation_id: UUID | None
    owner_epoch: UUID | None
    binding: LaunchBinding | None


@dataclass(frozen=True, slots=True)
class ClaimReceipt:
    claim: WorkerClaim | None
    state: RunState
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class HeartbeatReceipt:
    accepted: bool
    state: RunState
    heartbeat_at: datetime | None


@dataclass(frozen=True, slots=True)
class QueuedRun:
    document_id: UUID
    run_id: UUID
