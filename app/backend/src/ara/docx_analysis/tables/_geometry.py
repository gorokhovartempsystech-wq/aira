"""Normalize direct grid intervals without allocating a dense grid or text view."""

import re

from ._models import PhysicalTable, TableBlock, TableCell, TableRow, budget


class Geometry:
    def __init__(self, context, limits):
        self.c, self.limits = context, limits
        self.blocks = 0

    def attrs(self, node, names=(), required=()):
        self.c.require(set(node.attrib) <= {self.c.ns + n for n in names}, node)
        self.c.require(all(self.c.ns + n in node.attrib for n in required), node)

    def container(self, node):
        self.c.require(not (node.text or "").strip(), node)
        self.c.require(all(not (n.tail or "").strip() for n in node), node)

    def leaf(self, node, names=(), required=()):
        self.attrs(node, names, required)
        self.c.require(not len(node) and not (node.text or "").strip(), node)

    def child_nodes(self, node):
        return node

    def children(self, node, prop, allowed, *, row=False):
        if row:
            self.attrs(node, {"rsidR", "rsidRPr", "rsidDel", "rsidTr"})
            self.c.require(
                all(re.fullmatch(r"[0-9a-fA-F]{8}", v) is not None for v in node.attrib.values()),
                node,
            )
        else:
            self.attrs(node)
        self.container(node)
        properties, children = None, []
        for i, child in enumerate(self.child_nodes(node)):
            name = self.c.name(child)
            if name == prop:
                self.c.require(i == 0 and properties is None, child)
                self.attrs(child)
                self.container(child)
                properties = child
            else:
                self.c.require(name in allowed, child, "unsupported_table_context")
                children.append(child)
        return properties, children

    def properties(self, node, names):
        result = {}
        if node is not None:
            for child in node:
                name = self.c.name(child)
                if name in names:
                    self.c.require(name not in result, child)
                    result[name] = child
        return result

    def number(self, node, default, *, positive=False):
        if node is None:
            return default
        self.leaf(node, {"val"}, {"val"})
        value = node.get(self.c.ns + "val")
        self.c.require(re.fullmatch(r"[+]?[0-9]{1,20}", value) is not None, node)
        number = int(value)
        self.c.require(number > 0 if positive else number >= 0, node)
        budget(number, self.limits.max_grid_columns)
        return number

    def merge(self, node):
        if node is None:
            return "none"
        self.leaf(node, {"val"})
        value = node.get(self.c.ns + "val", "continue")
        self.c.require(value in ("restart", "continue"), node)
        return value

    def cell(self, node, start, previous, active):
        properties, blocks = self.children(node, "tcPr", {"p", "tbl"})
        self.c.require(bool(blocks), node, "unsupported_table_context")
        self.blocks += len(blocks)
        budget(self.blocks, self.limits.max_blocks)
        props = self.properties(properties, {"gridSpan", "vMerge"})
        span = self.number(props.get("gridSpan"), 1, positive=True)
        budget(start + span, self.limits.max_grid_columns)
        merge = self.merge(props.get("vMerge"))
        origin = self.c.anchors[node]
        interval = (start, span)
        if merge == "continue":
            self.c.require(interval in previous, props["vMerge"], "invalid_vertical_merge")
            origin = previous[interval]
        if merge != "none":
            active[interval] = origin
        return TableCell(
            self.c.anchors[node],
            self.c.optional_anchor(properties),
            start,
            span,
            merge,
            origin,
            tuple(
                TableBlock("paragraph" if self.c.name(n) == "p" else "table", self.c.anchors[n])
                for n in blocks
            ),
        )

    def grid_columns(self, grid):
        self.attrs(grid)
        self.container(grid)
        self.c.require(bool(len(grid)), grid, "unresolved_table_grid")
        budget(len(grid), self.limits.max_grid_columns)
        for column in grid:
            self.c.require(self.c.name(column) == "gridCol", column, "unsupported_table_context")
            self.leaf(column, {"w"})
        return tuple(grid)

    def table(self, node):
        properties, children = self.children(node, "tblPr", {"tblGrid", "tr"})
        grids = [n for n in children if self.c.name(n) == "tblGrid"]
        self.c.require(bool(grids), node, "unresolved_table_grid")
        self.c.require(len(grids) == 1 and children[0] is grids[0], node)
        grid, rows = grids[0], children[1:]
        columns = self.grid_columns(grid)
        self.c.require(bool(rows), node, "unsupported_table_context")
        result, previous = [], {}
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
            budget(start + after, self.limits.max_grid_columns)
            self.c.require(start + after == len(columns), row, "unresolved_table_grid")
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
        parent = self.c.parents[node]
        return PhysicalTable(
            self.c.anchors[node],
            self.c.anchors[parent] if parent is not self.c.body else None,
            self.c.optional_anchor(properties),
            self.c.anchors[grid],
            tuple(self.c.anchors[n] for n in columns),
            tuple(result),
        )
