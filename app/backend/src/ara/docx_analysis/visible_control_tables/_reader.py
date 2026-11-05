"""Visit original table/control hierarchy using independently proven physical subjects."""

from ara.docx_analysis.grid_tables import GridTableLimits, TableCatalogError
from ara.docx_analysis.tables._context import Blocked
from ara.docx_analysis.visible_controls._reader import ControlReader
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_stories._parse import caps
from ara.docx_analysis.visible_stories._proofs import TableProof

from ._context import ControlContext
from ._geometry import ControlGeometry


class TableControlReader(ControlReader):
    def __init__(self, *args, section_catalog, **kwargs):
        self.control_cache, self.current_flow = {}, None
        self.section_catalog = section_catalog
        super().__init__(*args, section_catalog=section_catalog, **kwargs)
        # Intermediate parent constructors received the legacy proof. Only the newly
        # proven catalog may authorize current properties or retained revisions here.
        self.histories = {h.anchor: h.kind for h in self.table_catalog.histories}
        self.table_revisions = {r.anchor: r.kind for r in self.table_catalog.revisions}
        self.proven_rows = {r.anchor: r for t in self.tables.values() for r in t.rows}
        self.proven_cells = {c.anchor: c for r in self.proven_rows.values() for c in r.cells}

    def control_content(self, node):
        if node not in self.control_cache:
            self.control_cache[node] = super().control_content(node)
        return self.control_cache[node]

    def control_context_type(self):
        return ControlContext

    def prepare_table_catalog(self, catalog):
        try:
            context = self.control_context_type()(self, self.section_catalog)
            geometry = ControlGeometry(context, GridTableLimits(**caps(self.limits)))
            tables = tuple(geometry.table(node) for node in context.tables)
            self.control_context = context
            return TableProof(
                "indexed" if tables else "absent",
                tables,
                tuple(context.histories),
                tuple(context.revisions),
            )
        except Blocked:
            return TableProof("blocked", (), (), ())
        except TableCatalogError:
            raise VisibleViewError("view_limit_exceeded") from None

    def block_plans(self, node):
        plans = super().block_plans(node)
        if self.name(node) == "p":
            self.flows[self.anchors[node]] = self.current_flow or self.anchors[self.body]
        return plans

    def control_block_plans(self, content):
        result = []
        for child in content:
            if self.name(child) not in ("p", "tbl", "sdt"):
                raise Refusal("unsupported_control_block")
            result.extend(self.block_plans(child))
        return result

    def structural_children(self, node, role, skip):
        result = []
        for child in node:
            if self.name(child) in skip:
                continue
            if child in self.control_context.controls:
                content = self.control_content(child)
                self.barrier(child)
                if content is not None:
                    result.extend(self.structural_children(content, role, set()))
                self.barrier(child)
            elif role == "row" and self.anchors[child] in self.proven_rows:
                row = self.proven_rows[self.anchors[child]]
                self.event("metadata", "table_row", child)
                self.read_properties(row.properties_anchor, "row")
                result.extend(self.structural_children(child, "cell", {"trPr"}))
            elif role == "cell" and child in self.control_context.deleted_cells:
                continue
            elif role == "cell" and self.anchors[child] in self.proven_cells:
                result.extend(self.cell_plans(child, self.proven_cells[self.anchors[child]]))
            else:
                raise Refusal("unsupported_control_context")
        return result

    def cell_plans(self, node, cell):
        self.event("metadata", "table_cell", node)
        self.read_properties(cell.properties_anchor, "cell")
        if cell.vertical_merge == "continue":
            self.continuation(cell)
            return []
        previous, self.current_flow = self.current_flow, cell.anchor
        try:
            result = []
            for child in node:
                if self.name(child) != "tcPr":
                    result.extend(self.block_plans(child))
            return result
        finally:
            self.current_flow = previous

    def table_plans(self, table):
        node = self.nodes[table.anchor]
        self.barrier(node)
        self.event("metadata", "table_structure", node)
        self.grid_event(table)
        self.read_properties(table.properties_anchor, "table")
        plans = self.structural_children(node, "row", {"tblPr", "tblGrid"})
        self.barrier(node)
        return plans
