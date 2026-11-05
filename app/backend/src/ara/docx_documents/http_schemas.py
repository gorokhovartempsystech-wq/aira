"""Deferred models for explicit local HTTP installation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MAX_REVISION = 9223372036854775807


class DocxMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)

    document_id: UUID
    title: str
    storage_revision: int = Field(ge=1, le=MAX_REVISION)
    current_sha256: str
    current_size_bytes: int = Field(ge=1, le=MAX_REVISION)
    created_at: datetime
    updated_at: datetime


class DocxList(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)

    items: list[DocxMetadata]
