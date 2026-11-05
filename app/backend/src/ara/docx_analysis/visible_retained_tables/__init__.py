"""Opt-in retained table text and mapping with source-preserved revisions."""

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

from ._api import build_retained_table_snapshot, map_retained_table_span, map_retained_table_spans

__all__ = [
    "build_retained_table_snapshot",
    "map_retained_table_spans",
    "map_retained_table_span",
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
]
