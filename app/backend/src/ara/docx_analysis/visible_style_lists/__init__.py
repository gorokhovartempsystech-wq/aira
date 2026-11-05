"""Direct and style-linked labels with original physical provenance."""

from ara.docx_analysis.visible_notes import (
    NoteReference,
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)

from ._api import build_style_list_snapshot, map_style_list_span, map_style_list_spans
from ._models import StyleListItem, StyleListSnapshot

__all__ = [
    "StyleListItem",
    "StyleListSnapshot",
    "NoteReference",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_style_list_snapshot",
    "map_style_list_span",
    "map_style_list_spans",
]
