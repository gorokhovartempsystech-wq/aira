"""Read controlled table flows without changing source paths, grid proofs or DOCX bytes."""

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
    build_control_table_snapshot,
    map_control_table_span,
    map_control_table_spans,
)

__all__ = [
    "NoteReference",
    "NoteSnapshot",
    "VisibleLimits",
    "VisibleMappedSpan",
    "VisibleSourceSlice",
    "VisibleSpanRequest",
    "VisibleViewError",
    "build_control_table_snapshot",
    "map_control_table_span",
    "map_control_table_spans",
]
