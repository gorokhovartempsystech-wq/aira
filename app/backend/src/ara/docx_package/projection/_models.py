"""Immutable structural records; source addresses apply only to identical bytes."""

from __future__ import annotations

from dataclasses import dataclass, field, fields

from .. import DocxSource


class ProjectionError(ValueError):
    """Stable diagnostics without source content or parser details."""

    _MESSAGES = {
        "invalid_input": "Invalid DOCX projection limits.",
        "projection_limit_exceeded": "DOCX projection exceeds a technical limit.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class ProjectionLimits:
    """Inclusive element count and depth bounds, including opaque subtrees."""

    max_nodes: int = 100000
    max_depth: int = 128

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or value <= 0:
                raise ProjectionError("invalid_input")


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    source_sha256: str
    part_name: str
    path: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Hyperlink:
    anchor: SourceAnchor
    relationship_id: str | None
    bookmark: str | None


@dataclass(frozen=True, slots=True)
class Span:
    kind: str
    anchor: SourceAnchor
    run_anchor: SourceAnchor | None
    text: str
    start: int
    end: int
    xml_space: str | None = None
    break_type: str | None = None
    hyperlink: Hyperlink | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Paragraph:
    anchor: SourceAnchor
    text: str
    spans: tuple[Span, ...]
    properties_anchor: SourceAnchor | None
    style_id: str | None
    numbering_id: str | None
    numbering_level: str | None
    has_opaque: bool
    kind: str = field(default="paragraph", init=False)


@dataclass(frozen=True, slots=True)
class OpaqueBlock:
    anchor: SourceAnchor
    reason: str
    element_name: str
    kind: str = field(default="opaque", init=False)


@dataclass(frozen=True, slots=True)
class Cell:
    anchor: SourceAnchor
    blocks: tuple[Paragraph | Table | OpaqueBlock, ...]
    properties_anchor: SourceAnchor | None
    grid_span: str | None
    vertical_merge: str | None


@dataclass(frozen=True, slots=True)
class Row:
    anchor: SourceAnchor
    cells: tuple[Cell, ...]
    properties_anchor: SourceAnchor | None


@dataclass(frozen=True, slots=True)
class Table:
    anchor: SourceAnchor
    rows: tuple[Row, ...]
    properties_anchor: SourceAnchor | None
    kind: str = field(default="table", init=False)


@dataclass(frozen=True, slots=True)
class Notice:
    code: str
    part_name: str
    anchor: SourceAnchor | None


@dataclass(frozen=True, slots=True)
class DocxProjection:
    source: DocxSource
    body_anchor: SourceAnchor
    blocks: tuple[Paragraph | Table | OpaqueBlock, ...]
    notices: tuple[Notice, ...]
    has_unprojected_content: bool
    coverage_scope: str = field(default="main-body-structural-v1", init=False)
