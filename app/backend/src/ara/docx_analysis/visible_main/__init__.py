"""Opt-in visible main reading and source-backed mapping; no application I/O."""

from ._build import build_visible_snapshot
from ._map import map_visible_span, map_visible_spans
from ._models import (
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

__all__ = [
    "build_visible_snapshot",
    "map_visible_spans",
    "map_visible_span",
    "VisibleLimits",
    "VisibleViewError",
    "VisibleSpanRequest",
    "VisibleSnapshot",
    "VisibleParagraphContext",
    "VisibleRunContext",
    "VisibleFragment",
    "VisiblePiece",
    "VisibleCoverage",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
]
