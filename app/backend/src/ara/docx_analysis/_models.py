"""Immutable, content-safe internal snapshot records; no wire deserialization."""

from dataclasses import dataclass, field, fields
from uuid import UUID

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-analysis/main-body-v1"


class SnapshotError(ValueError):
    """Stable diagnostics that never interpolate document content."""

    _MESSAGES = {
        "invalid_input": "Invalid analysis snapshot input or limits.",
        "source_mismatch": "DOCX source hash does not match.",
        "snapshot_limit_exceeded": "Analysis snapshot exceeds a technical limit.",
        "invalid_snapshot": "Invalid analysis snapshot.",
        "unknown_fragment": "Unknown analysis fragment.",
        "invalid_span": "Invalid analysis span or quote.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class SnapshotLimits:
    max_fragments: int = 10000
    max_text_characters: int = 1000000
    max_segments: int = 100000
    max_coverage_items: int = 10000

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, f.name)) is not int or getattr(self, f.name) <= 0
            for f in fields(self)
        ):
            raise SnapshotError("invalid_input")


@dataclass(frozen=True, slots=True)
class AnalysisSegment:
    kind: str
    anchor: SourceAnchor
    run_anchor: SourceAnchor | None
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class AnalysisFragment:
    fragment_id: str
    paragraph_anchor: SourceAnchor
    ancestry: tuple[SourceAnchor, ...]
    text: str = field(repr=False)
    analysis_start: int
    analysis_end: int
    segments: tuple[AnalysisSegment, ...]


@dataclass(frozen=True, slots=True)
class CoverageItem:
    status: str
    code: str
    part_name: str
    anchor: SourceAnchor | None
    fragment_id: str | None


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    document_id: UUID
    storage_revision: int
    source_sha256: str
    extractor_version: str
    main_part: str
    body_anchor: SourceAnchor
    fragments: tuple[AnalysisFragment, ...] = field(repr=False)
    analysis_text: str = field(repr=False)
    coverage: tuple[CoverageItem, ...]
    has_unprojected_content: bool
    complete: bool
    text_sha256: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class SourceSlice:
    kind: str
    anchor: SourceAnchor
    run_anchor: SourceAnchor | None
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class MappedSpan:
    fragment_id: str
    paragraph_anchor: SourceAnchor
    start: int
    end: int
    slices: tuple[SourceSlice, ...]
