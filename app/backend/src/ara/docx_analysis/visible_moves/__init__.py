"""Opt-in final inline move reader; native parity and runtime admission are separate."""

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

from ._api import build_move_snapshot, map_move_span, map_move_spans

__all__ = [
    "build_move_snapshot",
    "map_move_span",
    "map_move_spans",
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
