"""Source-bound visible text across current main/header/footer stories."""

from ara.docx_analysis.visible_main import (
    VisibleCoverage,
    VisibleFragment,
    VisibleLimits,
    VisibleMappedSpan,
    VisibleParagraphContext,
    VisiblePiece,
    VisibleRunContext,
    VisibleSnapshot,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)

from ._api import build_story_snapshot, map_story_span, map_story_spans

__all__ = [
    "VisibleCoverage",
    "VisibleFragment",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleParagraphContext",
    "VisiblePiece",
    "VisibleRunContext",
    "VisibleSnapshot",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_story_snapshot",
    "map_story_span",
    "map_story_spans",
]
