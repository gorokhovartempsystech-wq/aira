"""Content-safe immutable final-view records, independent of editable sessions."""

from dataclasses import dataclass, field, fields
from uuid import UUID

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-analysis/final-main-v1"
POLICY = "docx-analysis-policy/final-no-comments-v1"


class FinalViewError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid final-view input or limits.",
        "source_mismatch": "Final-view source hash does not match.",
        "view_limit_exceeded": "Final view exceeds a technical limit.",
        "invalid_snapshot": "Invalid final-view snapshot.",
        "unknown_fragment": "Unknown final-view fragment.",
        "invalid_span": "Invalid final-view span or quote.",
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


@dataclass(frozen=True, slots=True)
class FinalViewLimits:
    max_nodes: int = 100000
    max_depth: int = 128
    max_paragraphs: int = 100000
    max_fragments: int = 10000
    max_pieces: int = 100000
    max_text_characters: int = 1000000
    max_coverage_items: int = 100000

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if type(value) is not int or not 1 <= value <= f.default:
                raise FinalViewError("invalid_input")


@dataclass(frozen=True, slots=True)
class FinalPiece:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    run_anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    start: int
    end: int
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class ParagraphJoin:
    left: SourceAnchor = field(repr=False)
    right: SourceAnchor = field(repr=False)
    marker: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class FinalFragment:
    fragment_id: str
    story_anchor: SourceAnchor = field(repr=False)
    flow_anchor: SourceAnchor = field(repr=False)
    paragraph_anchors: tuple[SourceAnchor, ...] = field(repr=False)
    text: str = field(repr=False)
    pieces: tuple[FinalPiece, ...] = field(repr=False)
    joins: tuple[ParagraphJoin, ...] = field(repr=False)
    analysis_start: int
    analysis_end: int


@dataclass(frozen=True, slots=True)
class FinalCoverage:
    status: str
    code: str
    part_name: str = field(repr=False)
    anchor: SourceAnchor | None = field(repr=False)
    fragment_id: str | None


@dataclass(frozen=True, slots=True)
class FinalSnapshot:
    document_id: UUID
    storage_revision: int
    source_sha256: str
    profile: str
    policy_version: str
    main_part: str = field(repr=False)
    fragments: tuple[FinalFragment, ...] = field(repr=False)
    analysis_text: str = field(repr=False)
    coverage: tuple[FinalCoverage, ...] = field(repr=False)
    complete: bool
    text_sha256: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class FinalSourceSlice:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    run_anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class FinalMappedSpan:
    fragment_id: str
    start: int
    end: int
    slices: tuple[FinalSourceSlice, ...] = field(repr=False)
