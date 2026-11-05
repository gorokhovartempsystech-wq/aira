"""Conditional selectors are metadata only after every selected style is proven."""

import re

from ara.docx_analysis.visible_main._reader import boolean, check
from ara.docx_analysis.visible_tables._properties import Properties

FLAGS = {
    "firstRow",
    "lastRow",
    "firstColumn",
    "lastColumn",
    "oddVBand",
    "evenVBand",
    "oddHBand",
    "evenHBand",
    "firstRowFirstColumn",
    "firstRowLastColumn",
    "lastRowFirstColumn",
    "lastRowLastColumn",
}


def conditional(reader, node):
    reader.leaf(node)
    reader.attrs(node, FLAGS | {"val"})
    value = reader.attr(node, "val")
    if value is not None:
        check(re.fullmatch(r"[01]{12}", value) is not None)
    for name in FLAGS:
        value = reader.attr(node, name)
        if value is not None:
            boolean(value)
    reader.event("metadata", "conditional_table_format", node)


class StyledProperties(Properties):
    def table_style(self, node):
        # The selector belongs to an actual table and was validated from this DOM.
        check(self.r.anchors[node] in self.r.proven_selectors)

    def extended(self, node, kind):
        name = self.r.name(node)
        if kind in ("row", "cell") and name == "cnfStyle":
            conditional(self.r, node)
        elif kind == "table" and name in ("tblStyleRowBandSize", "tblStyleColBandSize"):
            self.formatting_leaf(node)
        else:
            super().extended(node, kind)
