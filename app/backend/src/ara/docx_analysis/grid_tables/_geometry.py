"""Derive only regular retained grids; never infer pixel widths or gap fallback."""

from ara.docx_analysis.retained_tables._geometry import RetainedGeometry
from ara.docx_analysis.tables._models import TableRow, budget

from ._models import GridTable


class GridGeometry(RetainedGeometry):
    def actual_columns(self, grid):
        if grid is None:
            return ()
        self.attrs(grid)
        self.container(grid)
        columns = tuple(n for n in grid if n not in self.c.history_nodes)
        budget(len(columns), self.limits.max_grid_columns)
        for column in columns:
            self.c.require(self.c.name(column) == "gridCol", column, "unsupported_table_context")
            self.leaf(column, {"w"})
        return columns

    def table(self, node):
        properties, children = self.children(node, "tblPr", {"tblGrid", "tr"})
        grids = [n for n in children if self.c.name(n) == "tblGrid"]
        self.c.require(len(grids) <= 1 and (not grids or children[0] is grids[0]), node)
        grid = grids[0] if grids else None
        rows = children[1:] if grid is not None else children
        columns = self.actual_columns(grid)
        self.c.require(bool(rows), node, "unsupported_table_context")
        result, previous, width, has_gaps = [], {}, None, False
        for row in rows:
            row_props, cells = self.children(row, "trPr", {"tc"}, row=True)
            self.c.require(bool(cells), row, "unsupported_table_context")
            props = self.properties(row_props, {"gridBefore", "gridAfter"})
            before, after = (self.number(props.get(n), 0) for n in ("gridBefore", "gridAfter"))
            start, records, active = before, [], {}
            for cell in cells:
                record = self.cell(cell, start, previous, active)
                records.append(record)
                start += record.column_span
            total = start + after
            budget(total, self.limits.max_grid_columns)
            if width is None:
                width = total
            self.c.require(total == width, row, "unresolved_table_grid")
            has_gaps = has_gaps or before != 0 or after != 0
            result.append(
                TableRow(
                    self.c.anchors[row],
                    self.c.optional_anchor(row_props),
                    before,
                    after,
                    tuple(records),
                )
            )
            previous = active
        self.c.require(len(columns) <= width, node, "unresolved_table_grid")
        if len(columns) == width:
            mode = "explicit"
        else:
            self.c.require(not has_gaps, node, "unresolved_table_grid")
            mode = "inferred" if grid is None else "augmented"
        parent = self.c.parents[node]
        return GridTable(
            self.c.anchors[node],
            self.c.anchors[parent] if parent is not self.c.body else None,
            self.c.optional_anchor(properties),
            self.c.optional_anchor(grid),
            tuple(self.c.anchors[n] for n in columns),
            tuple(result),
            mode,
            width,
        )
