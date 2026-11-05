"""Original-source unlisted paragraphs, pagination defaults and inactive list definitions."""

from ara.docx_analysis.visible_notes import (
    NoteReference,
    NoteSnapshot,
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)

from ._api import build_unlisted_snapshot, map_unlisted_span, map_unlisted_spans

__all__ = [
    "NoteReference",
    "NoteSnapshot",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_unlisted_snapshot",
    "map_unlisted_span",
    "map_unlisted_spans",
]
