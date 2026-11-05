"""Pure current table geometry; historical property payload stays in the source."""

from ara.docx_analysis.tables import (
    PhysicalTable,
    TableBlock,
    TableCatalogError,
    TableCell,
    TableIssue,
    TableRow,
)

from ._models import CurrentTableCatalog, CurrentTableLimits, TablePropertyHistory
from ._read import read_current_table_catalog

__all__ = [
    "CurrentTableCatalog",
    "CurrentTableLimits",
    "PhysicalTable",
    "TableBlock",
    "TableCatalogError",
    "TableCell",
    "TableIssue",
    "TablePropertyHistory",
    "TableRow",
    "read_current_table_catalog",
]
