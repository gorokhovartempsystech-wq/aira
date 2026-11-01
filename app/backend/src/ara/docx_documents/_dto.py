"""Detached snapshots of exact DOCX bytes and finite storage metadata."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

MAX_REVISION = 9223372036854775807


def valid_title(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 200
        and bool(value.strip())
        and "\x00" not in value
        and not any(0xD800 <= ord(char) <= 0xDFFF for char in value)
    )


def valid_integer(value: object, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _hash(value: object) -> bool:
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _metadata(value: "StoredDocx | DocxSummary") -> None:
    if (
        not isinstance(value.document_id, UUID)
        or not valid_title(value.title)
        or not valid_integer(value.storage_revision, 1, MAX_REVISION)
        or not _hash(value.current_sha256)
        or any(
            not isinstance(date, datetime) or date.utcoffset() is None
            for date in (value.created_at, value.updated_at)
        )
    ):
        raise ValueError("Invalid stored DOCX metadata")


@dataclass(frozen=True, slots=True)
class StoredDocx:
    document_id: UUID
    title: str
    original_data: bytes = field(repr=False)
    original_sha256: str
    current_data: bytes = field(repr=False)
    current_sha256: str
    storage_revision: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _metadata(self)
        if (
            not _hash(self.original_sha256)
            or type(self.original_data) is not bytes
            or type(self.current_data) is not bytes
            or not self.original_data
            or not self.current_data
        ):
            raise ValueError("Invalid stored DOCX metadata")


@dataclass(frozen=True, slots=True)
class DocxSummary:
    document_id: UUID
    title: str
    storage_revision: int
    current_sha256: str
    current_size_bytes: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _metadata(self)
        if not valid_integer(self.current_size_bytes, 1, MAX_REVISION):
            raise ValueError("Invalid stored DOCX metadata")
