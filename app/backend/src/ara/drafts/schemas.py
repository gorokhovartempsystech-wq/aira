"""Detached draft snapshots, preserving the complete editor text."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

MAX_REVISION = 9223372036854775807


def _valid_text(value: str) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Expected text without NUL")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Expected valid Unicode") from None
    return value


class DraftSnapshot(BaseModel):
    # Building a Pydantic validator may discover installed plugins via file I/O.
    # Keep that work at the first explicit API call, never at package import.
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, from_attributes=True, defer_build=True
    )

    document_id: UUID
    base_version_id: UUID
    revision: int = Field(gt=0, le=MAX_REVISION)
    content_markdown: str
    updated_at: AwareDatetime

    @field_validator("content_markdown")
    @classmethod
    def valid_text(cls, value: str) -> str:
        return _valid_text(value)
