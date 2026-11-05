"""Source-bound neutral table styles; not a final text or Word coverage claim."""

from ._models import (
    TableStyleCatalog,
    TableStyleDefinition,
    TableStyleError,
    TableStyleIssue,
    TableStyleLimits,
    TableStyleRegion,
)
from ._read import read_table_style_catalog

__all__ = [
    "read_table_style_catalog",
    "TableStyleCatalog",
    "TableStyleDefinition",
    "TableStyleError",
    "TableStyleIssue",
    "TableStyleLimits",
    "TableStyleRegion",
]
