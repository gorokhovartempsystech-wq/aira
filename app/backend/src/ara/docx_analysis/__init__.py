"""Source-exact DOCX analysis preparation; not a model or coverage of all Word stories."""

from ._models import (
    AnalysisFragment,
    AnalysisSegment,
    AnalysisSnapshot,
    CoverageItem,
    MappedSpan,
    SnapshotError,
    SnapshotLimits,
    SourceSlice,
)
from .inventory import (
    AnalysisPolicy,
    DocxInventory,
    InventoryError,
    InventoryLimits,
    InventoryPart,
    InventoryRelationship,
    inventory_docx,
)
from .snapshot import build_snapshot, map_span

__all__ = [
    "AnalysisFragment",
    "AnalysisSegment",
    "AnalysisSnapshot",
    "CoverageItem",
    "MappedSpan",
    "SnapshotError",
    "SnapshotLimits",
    "SourceSlice",
    "build_snapshot",
    "map_span",
    "AnalysisPolicy",
    "DocxInventory",
    "InventoryError",
    "InventoryLimits",
    "InventoryPart",
    "InventoryRelationship",
    "inventory_docx",
]
