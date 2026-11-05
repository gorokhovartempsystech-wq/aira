"""Pure visible note stories and exact source mapping, not application admission."""

from ara.docx_analysis.visible_main import (
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)

from ._api import build_note_snapshot, map_note_span, map_note_spans
from ._models import NoteReference, NoteSnapshot

__all__ = [
    "NoteReference",
    "NoteSnapshot",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_note_snapshot",
    "map_note_span",
    "map_note_spans",
]
