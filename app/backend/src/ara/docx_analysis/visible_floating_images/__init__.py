"""Floating raster metadata with original-source visibility and text mapping."""

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
    build_floating_image_snapshot,
    map_floating_image_span,
    map_floating_image_spans,
)

__all__ = [
    "NoteReference",
    "NoteSnapshot",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_floating_image_snapshot",
    "map_floating_image_span",
    "map_floating_image_spans",
]
