"""Direct single-level list labels, independent of literal original text slices."""

from ara.docx_analysis.visible_notes import (
    NoteReference,
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)

from ._api import build_list_snapshot, map_list_span, map_list_spans
from ._models import ListItem, ListSnapshot

__all__ = [
    "ListItem",
    "ListSnapshot",
    "NoteReference",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_list_snapshot",
    "map_list_span",
    "map_list_spans",
]
