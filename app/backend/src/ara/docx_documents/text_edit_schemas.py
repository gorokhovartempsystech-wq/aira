"""Strict deferred wire records for one anchored manual text edit."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._dto import MAX_REVISION


class TextEditAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    part_name: str = Field(min_length=1, max_length=1024)
    path: list[Annotated[int, Field(ge=0, le=100000)]] = Field(min_length=1, max_length=128)


class TextEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)

    expected_storage_revision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    anchor: TextEditAnchor
    expected_text: str = Field(max_length=100000)
    replacement_text: str = Field(max_length=100000)

    @field_validator("expected_storage_revision")
    @classmethod
    def revision_bound(cls, value):
        if not 1 <= int(value) <= MAX_REVISION - 1:
            raise ValueError("Invalid revision")
        return value


class TextEditReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)

    document_id: UUID
    title: str
    storage_revision: str
    current_sha256: str
    current_size_bytes: int
    created_at: datetime
    updated_at: datetime
