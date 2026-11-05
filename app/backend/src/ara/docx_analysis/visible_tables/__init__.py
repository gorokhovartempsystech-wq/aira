"""Opt-in final table flows; style, native rendering and application gates are explicit."""

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

from ._api import build_table_snapshot, map_table_span, map_table_spans

__all__ = [
    "build_table_snapshot",
    "map_table_spans",
    "map_table_span",
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
