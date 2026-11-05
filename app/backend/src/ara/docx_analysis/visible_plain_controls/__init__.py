"""Saved plain-text controls with original-source visibility and mapping."""

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
    build_plain_control_snapshot,
    map_plain_control_span,
    map_plain_control_spans,
)

__all__ = [
    "NoteReference",
    "NoteSnapshot",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_plain_control_snapshot",
    "map_plain_control_span",
    "map_plain_control_spans",
]
