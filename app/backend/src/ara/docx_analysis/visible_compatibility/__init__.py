"""Visible selected Word content, preserving original-source mapping and refusal gates."""

from ara.docx_analysis.visible_main import (
    VisibleLimits,
    VisibleMappedSpan,
    VisibleSourceSlice,
    VisibleSpanRequest,
    VisibleViewError,
)
from ara.docx_analysis.visible_notes import NoteSnapshot

from ._api import (
    build_compatibility_snapshot,
    map_compatibility_span,
    map_compatibility_spans,
)

__all__ = [
    "NoteSnapshot",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_compatibility_snapshot",
    "map_compatibility_span",
    "map_compatibility_spans",
]
