"""Detached checkpoint storage records without package contents in diagnostics."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ara.docx_package.checkpoint import CheckpointMetadata

from ._dto import MAX_REVISION, StoredDocx, _hash, valid_integer


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    document_id: UUID
    checkpoint_revision: int
    format_version: int
    phase: str
    base_storage_revision: int | None
    base_sha256: str | None
    working_data: bytes | None = field(repr=False)
    working_sha256: str | None
    metadata: CheckpointMetadata | None = field(repr=False)
    last_request_id: UUID | None
    last_request_sha256: str | None
    updated_at: datetime

    def __post_init__(self):
        valid = (
            type(self.document_id) is UUID
            and valid_integer(self.checkpoint_revision, 1, MAX_REVISION)
            and type(self.format_version) is int
            and self.format_version == 1
            and type(self.phase) is str
            and self.phase in ("empty", "working", "pending")
            and type(self.updated_at) is datetime
            and self.updated_at.utcoffset() is not None
            and (
                (self.last_request_id is None and self.last_request_sha256 is None)
                or (type(self.last_request_id) is UUID and _hash(self.last_request_sha256))
            )
        )
        if self.phase == "empty":
            valid = valid and all(
                v is None
                for v in (
                    self.base_storage_revision,
                    self.base_sha256,
                    self.working_data,
                    self.working_sha256,
                    self.metadata,
                )
            )
        else:
            valid = (
                valid
                and valid_integer(self.base_storage_revision, 1, MAX_REVISION)
                and _hash(self.base_sha256)
                and _hash(self.working_sha256)
                and type(self.working_data) is bytes
                and 1 <= len(self.working_data) <= 33554432
                and type(self.metadata) is CheckpointMetadata
            )
            if valid:
                self.metadata.__post_init__()
                valid = (self.phase == "pending") == (self.metadata.pending is not None)
        if not valid:
            raise ValueError("Invalid stored DOCX checkpoint")


@dataclass(frozen=True, slots=True)
class CheckpointSnapshot:
    document: StoredDocx = field(repr=False)
    checkpoint: CheckpointRecord = field(repr=False)

    def __post_init__(self):
        if (
            type(self.document) is not StoredDocx
            or type(self.checkpoint) is not CheckpointRecord
            or self.document.document_id != self.checkpoint.document_id
        ):
            raise ValueError("Invalid stored DOCX checkpoint snapshot")
