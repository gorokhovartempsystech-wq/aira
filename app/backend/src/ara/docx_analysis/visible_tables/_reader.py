"""Source-order cell flows; no inferred grid, cross-cell join or payload deletion."""

from functools import partial

from ara.docx_analysis import moves, tables
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_moves._reader import MoveReader

from ._properties import Properties


def read_catalogs(data, source, limits):
    caps = dict(
        max_xml_nodes=limits.max_xml_nodes,
        max_xml_depth=limits.max_xml_depth,
        max_xml_characters=limits.max_xml_characters,
    )
    # Table-specific bounds precede any catalog or reader semantic allocation.
    try:
        table_catalog = tables.read_table_catalog(
            data, source_sha256=source.sha256, limits=tables.TableLimits(**caps)
        )
    except tables.TableCatalogError as exc:
        code = "view_limit_exceeded" if exc.code == "table_limit_exceeded" else exc.code
        raise VisibleViewError(code) from None
    try:
        move_catalog = moves.read_move_catalog(
            data, source_sha256=source.sha256, limits=moves.MoveLimits(**caps)
        )
    except moves.MoveCatalogError as exc:
        code = "view_limit_exceeded" if exc.code == "move_limit_exceeded" else exc.code
        raise VisibleViewError(code) from None
    return table_catalog, move_catalog


def prepare_reader(data, source, limits):
    table_catalog, move_catalog = read_catalogs(data, source, limits)
    return partial(TableReader, catalog=move_catalog, table_catalog=table_catalog)


class TableReader(MoveReader):
    def __init__(self, root, source, limits, *, catalog, table_catalog):
        super().__init__(root, source, limits, catalog=catalog)
        table_catalog = self.prepare_table_catalog(table_catalog)
        self.table_catalog = table_catalog
        self.tables = {t.anchor: t for t in table_catalog.tables}
        self.nodes = {anchor: node for node, anchor in self.anchors.items()}
        self.flows = {}

    def prepare_table_catalog(self, catalog):
        return catalog

    def validate_style_context(self, catalog):
        if self.tables and any(s.style_type == "table" and s.is_default for s in catalog.styles):
            raise Refusal("implicit_table_style")

    def flow_anchor(self, paragraph_anchor):
        return self.flows[paragraph_anchor]

    def plans(self):
        if self.table_catalog.status == "blocked":
            raise Refusal("table_catalog_blocked")
        return super().plans()

    def block_plans(self, node):
        if self.name(node) == "tbl":
            return self.table_plans(self.tables[self.anchors[node]])
        plans = super().block_plans(node)
        for p in plans:
            self.flows[self.anchors[p.node]] = self.anchors[self.body]
        return plans

    def continuation(self, cell):
        for block in cell.blocks:
            node = self.nodes[block.anchor]
            if block.kind != "paragraph" or len(node) or (node.text or "").strip():
                raise Refusal("unresolved_merged_cell_content")
            try:
                self.rsids(node, paragraph=True)
                self.container(node)
            except Refusal:
                raise Refusal("unresolved_merged_cell_content") from None
        self.event("excluded", "merged_cell_continuation", self.nodes[cell.anchor])

    def read_properties(self, anchor, kind):
        Properties(self).read(anchor, kind)

    def grid_event(self, table):
        self.event("metadata", "table_grid", self.nodes[table.grid_anchor])

    def table_plans(self, table):
        self.event("metadata", "table_structure", self.nodes[table.anchor])
        self.grid_event(table)
        self.read_properties(table.properties_anchor, "table")
        result = []
        for row in table.rows:
            self.event("metadata", "table_row", self.nodes[row.anchor])
            self.read_properties(row.properties_anchor, "row")
            for cell in row.cells:
                self.event("metadata", "table_cell", self.nodes[cell.anchor])
                self.read_properties(cell.properties_anchor, "cell")
                if cell.vertical_merge == "continue":
                    self.continuation(cell)
                    continue
                for block in cell.blocks:
                    if block.kind == "table":
                        result.extend(self.table_plans(self.tables[block.anchor]))
                    else:
                        plans = super().block_plans(self.nodes[block.anchor])
                        for p in plans:
                            self.flows[self.anchors[p.node]] = cell.anchor
                        result.extend(plans)
        return result
