"""Retained current table cells and source-addressed revision facts."""

from dataclasses import dataclass, field

from ara.docx_analysis.current_tables import CurrentTableLimits, TablePropertyHistory
from ara.docx_analysis.tables import PhysicalTable, TableIssue
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-tables/retained-current-grid-v1"


@dataclass(frozen=True, slots=True)
class RetainedTableLimits(CurrentTableLimits):
    max_revisions: int = 20000


@dataclass(frozen=True, slots=True)
class TableRevision:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    owner_anchor: SourceAnchor = field(repr=False)
    subject_anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class RetainedTableCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    tables: tuple[PhysicalTable, ...] = field(repr=False)
    histories: tuple[TablePropertyHistory, ...] = field(repr=False)
    revisions: tuple[TableRevision, ...] = field(repr=False)
    issues: tuple[TableIssue, ...] = field(repr=False)
    catalog_sha256: str
