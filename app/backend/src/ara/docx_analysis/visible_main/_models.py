"""Detached source-bound visible main records, independent of legacy snapshots."""

from dataclasses import dataclass, field, fields
from uuid import UUID

from ara.docx_analysis.visibility import (
    StyleContext,
    StyleContextError,
    StyleContextLimits,
    VisibilityProperties,
)
from ara.docx_analysis.visibility.rules import RunVisibility
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-analysis/final-visible-main-v1"
POLICY = "docx-analysis-policy/final-visible-no-comments-v2"


class VisibleViewError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid visible-view input or limits.",
        "source_mismatch": "Visible-view source hash does not match.",
        "view_limit_exceeded": "Visible view exceeds a technical limit.",
        "invalid_snapshot": "Invalid visible-view snapshot.",
        "unknown_fragment": "Unknown visible-view fragment.",
        "invalid_span": "Invalid visible-view span or quote.",
    }

    def __init__(self, code: str):
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)


def budget(count, maximum):
    if count > maximum:
        raise VisibleViewError("view_limit_exceeded")


@dataclass(frozen=True, slots=True)
class VisibleLimits:
    max_xml_nodes: int = 100000
    max_xml_depth: int = 128
    max_xml_characters: int = 8388608
    max_paragraphs: int = 10000
    max_runs: int = 10000
    max_pieces: int = 100000
    max_text_characters: int = 1000000
    max_coverage_items: int = 100000
    max_span_requests: int = 10000
    max_requested_characters: int = 1000000
    max_mapped_slices: int = 100000
    max_manifest_bytes: int = 33554432
    styles: StyleContextLimits = field(default_factory=StyleContextLimits)

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name, None)
            if f.name == "styles":
                if type(value) is not StyleContextLimits:
                    raise VisibleViewError("invalid_input")
                try:
                    value.__post_init__()
                except (StyleContextError, AttributeError):
                    raise VisibleViewError("invalid_input") from None
            elif type(value) is not int or not 1 <= value <= f.default:
                raise VisibleViewError("invalid_input")


def checked_limits(limits):
    if limits is None:
        limits = VisibleLimits()
    if type(limits) is not VisibleLimits:
        raise VisibleViewError("invalid_input")
    limits.__post_init__()
    return limits


@dataclass(frozen=True, slots=True)
class VisibleParagraphContext:
    paragraph_anchor: SourceAnchor = field(repr=False)
    style_reference_anchor: SourceAnchor | None = field(repr=False)
    requested_style_id: str | None = field(repr=False)
    resolved_style_id: str | None = field(repr=False)
    mark_properties: VisibilityProperties = field(repr=False)


@dataclass(frozen=True, slots=True)
class VisibleRunContext:
    run_anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    style_reference_anchor: SourceAnchor | None = field(repr=False)
    requested_style_id: str | None = field(repr=False)
    resolved_style_id: str | None = field(repr=False)
    direct_properties: VisibilityProperties = field(repr=False)
    visibility: RunVisibility = field(repr=False)


@dataclass(frozen=True, slots=True)
class VisiblePiece:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    run_anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    start: int
    end: int
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class VisibleFragment:
    fragment_id: str
    story_anchor: SourceAnchor = field(repr=False)
    flow_anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    text: str = field(repr=False)
    pieces: tuple[VisiblePiece, ...] = field(repr=False)
    analysis_start: int
    analysis_end: int


@dataclass(frozen=True, slots=True)
class VisibleCoverage:
    status: str
    code: str
    part_name: str = field(repr=False)
    anchor: SourceAnchor | None = field(repr=False)
    fragment_id: str | None


@dataclass(frozen=True, slots=True)
class VisibleSnapshot:
    document_id: UUID
    storage_revision: int
    source_sha256: str
    profile: str
    policy_version: str
    main_part: str = field(repr=False)
    style_context: StyleContext = field(repr=False)
    paragraphs: tuple[VisibleParagraphContext, ...] = field(repr=False)
    runs: tuple[VisibleRunContext, ...] = field(repr=False)
    fragments: tuple[VisibleFragment, ...] = field(repr=False)
    analysis_text: str = field(repr=False)
    coverage: tuple[VisibleCoverage, ...] = field(repr=False)
    complete: bool
    text_sha256: str
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class VisibleSpanRequest:
    fragment_id: str
    start: int
    end: int
    quote: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class VisibleSourceSlice:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    run_anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class VisibleMappedSpan:
    fragment_id: str
    start: int
    end: int
    slices: tuple[VisibleSourceSlice, ...] = field(repr=False)
