"""Immutable physical definitions; none of these records asserts visible note use."""

from dataclasses import dataclass, field, fields

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-notes/original-definitions-v1"


class NoteCatalogError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid note-catalog input or limits.",
        "source_mismatch": "Note-catalog source hash does not match.",
        "note_limit_exceeded": "Note catalog exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code = code if type(code) is str and code in self._MESSAGES else "invalid_input"
        super().__init__(self._MESSAGES[self.code])


def budget(count, maximum):
    if count > maximum:
        raise NoteCatalogError("note_limit_exceeded")


@dataclass(frozen=True, slots=True)
class NoteLimits:
    max_xml_nodes: int = 100000
    max_xml_depth: int = 128
    max_xml_characters: int = 8388608
    max_parts: int = 128
    max_notes: int = 10000
    max_manifest_bytes: int = 33554432

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name, None)
            if type(value) is not int or not 1 <= value <= f.default:
                raise NoteCatalogError("invalid_input")


@dataclass(frozen=True, slots=True)
class NoteDefinition:
    note_id: int = field(repr=False)
    note_type: str
    anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class NotePart:
    kind: str
    part_name: str = field(repr=False)
    root_anchor: SourceAnchor = field(repr=False)
    linked: bool
    definitions: tuple[NoteDefinition, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class NoteIssue:
    code: str
    anchor: SourceAnchor | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class NoteCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    parts: tuple[NotePart, ...] = field(repr=False)
    issues: tuple[NoteIssue, ...] = field(repr=False)
    catalog_sha256: str


class Refused(Exception):
    def __init__(self, code, anchor=None):
        self.issue = NoteIssue(code, anchor)
        super().__init__(code)


def require(condition, code, anchor=None):
    if not condition:
        raise Refused(code, anchor)
