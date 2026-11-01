"""Strict draft wire models; schema construction is deferred until route installation."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from ara.drafts.schemas import MAX_REVISION, _valid_text


def _http_uuid(value: str) -> UUID:
    """Accept Python UUID string forms without coercing other JSON types."""
    if not isinstance(value, str):
        raise ValueError("Expected a UUID string")
    return UUID(value)


HttpUUID = Annotated[UUID, BeforeValidator(_http_uuid)]


class PutDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)

    expected_revision: int = Field(ge=0, le=MAX_REVISION - 1)
    base_version_id: HttpUUID
    content_markdown: str

    @field_validator("content_markdown")
    @classmethod
    def valid_text(cls, value: str) -> str:
        return _valid_text(value)


class DraftErrorResponse(BaseModel):
    """The envelope emitted by the existing local document error handlers."""

    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)

    code: str
    message: str
    retryable: bool
    request_id: UUID
