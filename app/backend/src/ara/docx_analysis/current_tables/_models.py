"""Source-addressed current geometry and opaque previous property envelopes."""

from dataclasses import dataclass, field

from ara.docx_analysis.tables import PhysicalTable, TableIssue, TableLimits
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-tables/current-properties-grid-v1"


@dataclass(frozen=True, slots=True)
class CurrentTableLimits(TableLimits):
    max_histories: int = 20000


@dataclass(frozen=True, slots=True)
class TablePropertyHistory:
    kind: str
    anchor: SourceAnchor = field(repr=False)
    owner_anchor: SourceAnchor = field(repr=False)
    previous_anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class CurrentTableCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    tables: tuple[PhysicalTable, ...] = field(repr=False)
    histories: tuple[TablePropertyHistory, ...] = field(repr=False)
    issues: tuple[TableIssue, ...] = field(repr=False)
    catalog_sha256: str
