"""Read-only final Word text with multiple original source ranges; no analysis runner."""

from ._build import build_final_snapshot
from ._map import map_final_span
from ._models import (
    FinalCoverage,
    FinalFragment,
    FinalMappedSpan,
    FinalPiece,
    FinalSnapshot,
    FinalSourceSlice,
    FinalViewError,
    FinalViewLimits,
    ParagraphJoin,
)
from .properties import build_properties_snapshot

__all__ = [
    "build_final_snapshot",
    "map_final_span",
    "FinalViewLimits",
    "FinalViewError",
    "FinalSnapshot",
    "FinalFragment",
    "FinalPiece",
    "ParagraphJoin",
    "FinalCoverage",
    "FinalMappedSpan",
    "FinalSourceSlice",
    "build_properties_snapshot",
]
