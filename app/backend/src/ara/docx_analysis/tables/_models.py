"""Direct-current physical records; never final visibility or layout claims."""

from dataclasses import dataclass, field, fields

from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-tables/main-physical-grid-v1"


class TableCatalogError(ValueError):
    _MESSAGES = {
        "invalid_input": "Invalid table-catalog input or limits.",
        "source_mismatch": "Table-catalog source hash does not match.",
        "table_limit_exceeded": "Table catalog exceeds a technical limit.",
    }

    def __init__(self, code):
        self.code = code if type(code) is str and code in self._MESSAGES else "invalid_input"
        super().__init__(self._MESSAGES[self.code])


def budget(count, maximum):
    if count > maximum:
        raise TableCatalogError("table_limit_exceeded")


@dataclass(frozen=True, slots=True)
class TableLimits:
    max_xml_nodes: int = 100000
    max_xml_depth: int = 128
    max_xml_characters: int = 8388608
    max_tables: int = 1000
    max_rows: int = 10000
    max_cells: int = 10000
    max_grid_columns: int = 1024
    max_table_depth: int = 16
    max_blocks: int = 20000
    max_manifest_bytes: int = 33554432

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name, None)
            if type(value) is not int or not 1 <= value <= item.default:
                raise TableCatalogError("invalid_input")


@dataclass(frozen=True, slots=True)
class TableBlock:
    kind: str
    anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableCell:
    anchor: SourceAnchor = field(repr=False)
    properties_anchor: SourceAnchor | None = field(repr=False)
    column_start: int
    column_span: int
    vertical_merge: str
    merge_origin: SourceAnchor = field(repr=False)
    blocks: tuple[TableBlock, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableRow:
    anchor: SourceAnchor = field(repr=False)
    properties_anchor: SourceAnchor | None = field(repr=False)
    grid_before: int
    grid_after: int
    cells: tuple[TableCell, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class PhysicalTable:
    anchor: SourceAnchor = field(repr=False)
    parent_cell_anchor: SourceAnchor | None = field(repr=False)
    properties_anchor: SourceAnchor | None = field(repr=False)
    grid_anchor: SourceAnchor = field(repr=False)
    grid_columns: tuple[SourceAnchor, ...] = field(repr=False)
    rows: tuple[TableRow, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableIssue:
    code: str
    anchor: SourceAnchor = field(repr=False)


@dataclass(frozen=True, slots=True)
class TableCatalog:
    source_sha256: str
    profile: str
    status: str
    main_part: str = field(repr=False)
    tables: tuple[PhysicalTable, ...] = field(repr=False)
    issues: tuple[TableIssue, ...] = field(repr=False)
    catalog_sha256: str
