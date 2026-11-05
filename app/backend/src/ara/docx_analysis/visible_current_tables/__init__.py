"""Opt-in current table text and mapping with source-preserved property histories."""

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

from ._api import build_current_table_snapshot, map_current_table_span, map_current_table_spans

__all__ = [
    "build_current_table_snapshot",
    "map_current_table_spans",
    "map_current_table_span",
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
