"""Direct multilevel list labels, independent of literal original text slices."""

from ara.docx_analysis.visible_notes import (
    NoteReference,
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)

from ._api import build_outline_snapshot, map_outline_span, map_outline_spans
from ._models import ListItem, OutlineSnapshot

__all__ = [
    "ListItem",
    "OutlineSnapshot",
    "NoteReference",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_outline_snapshot",
    "map_outline_span",
    "map_outline_spans",
]
