"""Metadata-only run summaries; source bytes are exposed only by get_source."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from ara.docx_analysis.storage_codec._models import counter, digest, uuid

ACTIVE = ("queued", "running", "cancel_requested")
TERMINAL = ("succeeded", "failed", "cancelled", "timed_out")


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: UUID
    document_id: UUID
    storage_revision: int
    accepted_order: int
    source_sha256: str
    snapshot_sha256: str
    profile: str
    policy_version: str
    execution_spec_sha256: str
    client_request_id: UUID
    start_kind: str
    retry_of_run_id: UUID | None
    status: str
    stage: str
    execution_kind: str
    created_at: datetime
    deadline_at: datetime
    finished_at: datetime | None

    def __post_init__(self):
        valid = all(uuid(v) for v in (self.run_id, self.document_id, self.client_request_id))
        valid = valid and counter(self.storage_revision) and counter(self.accepted_order)
        valid = valid and all(
            digest(v)
            for v in (self.source_sha256, self.snapshot_sha256, self.execution_spec_sha256)
        )
        valid = valid and all(
            type(v) is str and re.fullmatch(r"[a-z0-9][a-z0-9/_.-]{0,127}", v)
            for v in (self.profile, self.policy_version)
        )
        valid = valid and type(self.status) is str and self.status in ACTIVE + TERMINAL
        valid = valid and type(self.start_kind) is str and self.start_kind in ("saved", "retry")
        valid = valid and (
            (self.start_kind == "saved" and self.retry_of_run_id is None)
            or (self.start_kind == "retry" and uuid(self.retry_of_run_id))
        )
        valid = (
            valid
            and type(self.execution_kind) is str
            and self.execution_kind in ("fixture", "local_model")
        )
        times = (self.created_at, self.deadline_at) + (
            (self.finished_at,) if self.finished_at is not None else ()
        )
        valid = valid and all(
            type(t) is datetime and t.tzinfo is not None and t.utcoffset() is not None
            for t in times
        )
        valid = valid and (self.finished_at is None or self.finished_at >= self.created_at)
        valid = valid and self.deadline_at == self.created_at + timedelta(seconds=300)
        valid = valid and (
            (self.status in ACTIVE and self.finished_at is None)
            or (self.status in TERMINAL and self.finished_at is not None)
        )
        stages = (
            "preparing_document",
            "loading_model",
            "analyzing",
            "validating_result",
            "finishing",
        )
        valid = (
            valid
            and type(self.stage) is str
            and (self.stage in stages if self.status == "running" else self.stage == self.status)
        )
        if not valid:
            raise ValueError("Invalid stored analysis metadata")


@dataclass(frozen=True, slots=True)
class StartOutcome:
    summary: RunSummary
    replayed: bool
