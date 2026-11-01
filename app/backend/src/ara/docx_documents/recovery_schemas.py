"""Strict working copy wire records; reuse the exact manual edit contract."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .text_edit_schemas import TextEditRequest

Token = Annotated[str, Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")]


class RecoveryPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", defer_build=True)
    edit: TextEditRequest
    operation_id: Token | None

    @field_validator("edit")
    @classmethod
    def jsonb_text(cls, edit):
        # PostgreSQL JSONB cannot represent NUL or unpaired UTF-16 surrogates.
        # Reject these before a transaction so a corrected copy can be retried.
        for value in (edit.expected_text, edit.replacement_text, edit.anchor.part_name):
            if "\x00" in value:
                raise ValueError("Unsupported text character")
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("Invalid Unicode text") from None
        return edit


class PutRecovery(RecoveryPayload):
    expected_token: Token | None
    token: Token

    @model_validator(mode="after")
    def different_token(self):
        if self.expected_token == self.token:
            raise ValueError("New token required")
        return self


class DeleteRecovery(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", defer_build=True)
    expected_token: Token


class RecoveryRecord(RecoveryPayload):
    token: Token
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def aware(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Timezone required")
        return value


class RecoveryEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", defer_build=True)
    document_id: UUID
    draft: RecoveryRecord | None
