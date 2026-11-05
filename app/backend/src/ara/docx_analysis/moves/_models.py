"""Detached structural facts; no claim of visible text or complete document coverage."""

from dataclasses import dataclass, field, fields

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-moves/main-inline-catalog-v1"


class MoveCatalogError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid move-catalog input or limits.",
        "source_mismatch": "Move-catalog source hash does not match.",
        "move_limit_exceeded": "Move catalog exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code = code if type(code) is str and code in self._MESSAGES else "invalid_input"
        super().__init__(self._MESSAGES[self.code])


@dataclass(frozen=True, slots=True)
class MoveLimits:
    max_xml_nodes: int = 100000
    max_xml_depth: int = 128
    max_xml_characters: int = 8388608
    max_ranges: int = 8192
    max_members: int = 10000

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or not 1 <= value <= item.default:
                raise MoveCatalogError("invalid_input")


@dataclass(frozen=True, slots=True)
class MoveMember:
    kind: str
    revision_id: int = field(repr=False)
    anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class MoveRange:
    kind: str
    range_id: int = field(repr=False)
    name: str = field(repr=False)
    start: SourceAnchor = field(repr=False)
    end: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    members: tuple[MoveMember, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class MovePair:
    name: str = field(repr=False)
    source: MoveRange = field(repr=False)
    destination: MoveRange = field(repr=False)


@dataclass(frozen=True, slots=True)
class MoveIssue:
    code: str
    anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class MoveCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    pairs: tuple[MovePair, ...] = field(repr=False)
    issues: tuple[MoveIssue, ...] = field(repr=False)
    catalog_sha256: str


def budget(count, maximum):
    if count > maximum:
        raise MoveCatalogError("move_limit_exceeded")
