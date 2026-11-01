"""Immutable, in-memory records for original DOCX packages."""

from dataclasses import dataclass, field, fields


class DocxError(ValueError):
    """A stable error without archive contents or parser diagnostics."""

    _MESSAGES = {
        "invalid_input": "Invalid DOCX input or limits.",
        "invalid_package": "Invalid DOCX package.",
        "unsupported_package": "Unsupported DOCX package.",
        "package_limit_exceeded": "DOCX package exceeds a technical limit.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class DocxLimits:
    """Inclusive technical bounds; these are not product text limits."""

    max_archive_bytes: int = 33554432
    max_entries: int = 4096
    max_part_bytes: int = 67108864
    max_total_uncompressed_bytes: int = 134217728
    max_xml_bytes: int = 8388608

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or value <= 0:
                raise DocxError("invalid_input")


@dataclass(frozen=True, slots=True)
class Entry:
    name: str
    content_type: str | None
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Relationship:
    source_part: str
    relationship_id: str
    relationship_type: str
    target: str
    target_mode: str
    resolved_part: str | None


@dataclass(frozen=True, slots=True)
class DocxSource:
    """Validated original bytes plus an inventory, not an editable document."""

    sha256: str
    size_bytes: int
    main_part: str
    entries: tuple[Entry, ...]
    relationships: tuple[Relationship, ...]
    _original: bytes = field(repr=False)
