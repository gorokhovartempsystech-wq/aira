"""Strict input and explicit wire representations for documents."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarkdownContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    content_markdown: str = Field(min_length=1, max_length=1_000_000)

    @field_validator("content_markdown")
    @classmethod
    def valid_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Expected nonempty text without NUL")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Expected valid Unicode") from None
        return value


class CreateDocument(MarkdownContent):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        return cls.valid_text(value)


class AppendVersion(MarkdownContent):
    document_id: UUID
    expected_version_id: UUID


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    current_version_id: UUID
    created_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentSummary]


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    parent_version_id: UUID | None
    content_markdown: str
    blocks: list[dict[str, str]]
    provenance: dict[str, Any]
    import_omissions: list[Any]
    created_at: datetime
