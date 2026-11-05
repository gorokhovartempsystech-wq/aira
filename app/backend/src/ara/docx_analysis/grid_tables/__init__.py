"""Pure current logical grid catalog with no fabricated XML column anchors."""

from ara.docx_analysis.current_tables import TablePropertyHistory
from ara.docx_analysis.retained_tables import TableRevision
from ara.docx_analysis.tables import TableBlock, TableCatalogError, TableCell, TableIssue, TableRow

from ._models import GridTable, GridTableCatalog, GridTableLimits
from ._read import read_grid_table_catalog

__all__ = [
    "GridTable",
    "GridTableCatalog",
    "GridTableLimits",
    "TableBlock",
    "TableCatalogError",
    "TableCell",
    "TableIssue",
    "TablePropertyHistory",
    "TableRevision",
    "TableRow",
    "read_grid_table_catalog",
]
