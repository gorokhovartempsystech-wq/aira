"""Pure retained table geometry; revisions never mutate the original source."""

from ara.docx_analysis.current_tables import TablePropertyHistory
from ara.docx_analysis.tables import (
    PhysicalTable,
    TableBlock,
    TableCatalogError,
    TableCell,
    TableIssue,
    TableRow,
)

from ._models import RetainedTableCatalog, RetainedTableLimits, TableRevision
from ._read import read_retained_table_catalog

__all__ = [
    "RetainedTableCatalog",
    "RetainedTableLimits",
    "PhysicalTable",
    "TableBlock",
    "TableCatalogError",
    "TableCell",
    "TableIssue",
    "TablePropertyHistory",
    "TableRow",
    "TableRevision",
    "read_retained_table_catalog",
]
