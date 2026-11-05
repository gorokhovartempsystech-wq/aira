"""Inline raster boundaries with original-source visibility and text mapping."""

from ara.docx_analysis.visible_notes import (
    NoteReference,
    NoteSnapshot,
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)

from ._api import (
    build_inline_image_snapshot,
    map_inline_image_span,
    map_inline_image_spans,
)

__all__ = [
    "NoteReference",
    "NoteSnapshot",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_inline_image_snapshot",
    "map_inline_image_span",
    "map_inline_image_spans",
]
