"""Ordinary package parts and style lists, retaining original source addresses."""

from ara.docx_analysis.visible_notes import (
    NoteReference,
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)
from ara.docx_analysis.visible_style_lists import StyleListItem

from ._api import build_word_snapshot, map_word_span, map_word_spans
from ._models import WordSnapshot

__all__ = [
    "StyleListItem",
    "WordSnapshot",
    "NoteReference",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_word_snapshot",
    "map_word_span",
    "map_word_spans",
]
