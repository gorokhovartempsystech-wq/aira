"""Keep existing grid nodes separate from derived logical column counts."""

from dataclasses import dataclass, field

from ara.docx_analysis.current_tables import TablePropertyHistory
from ara.docx_analysis.retained_tables import RetainedTableLimits, TableRevision
from ara.docx_analysis.tables import TableIssue, TableRow
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-tables/current-resolved-grid-v1"


@dataclass(frozen=True, slots=True)
class GridTableLimits(RetainedTableLimits):
    pass


@dataclass(frozen=True, slots=True)
class GridTable:
    anchor: SourceAnchor = field(repr=False)
    parent_cell_anchor: SourceAnchor | None = field(repr=False)
    properties_anchor: SourceAnchor | None = field(repr=False)
    grid_anchor: SourceAnchor | None = field(repr=False)
    grid_columns: tuple[SourceAnchor, ...] = field(repr=False)
    rows: tuple[TableRow, ...] = field(repr=False)
    grid_mode: str
    column_count: int


@dataclass(frozen=True, slots=True)
class GridTableCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    tables: tuple[GridTable, ...] = field(repr=False)
    histories: tuple[TablePropertyHistory, ...] = field(repr=False)
    revisions: tuple[TableRevision, ...] = field(repr=False)
    issues: tuple[TableIssue, ...] = field(repr=False)
    catalog_sha256: str
