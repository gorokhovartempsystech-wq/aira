"""Closed direct-format accounting; unknown style/visibility is never guessed."""

from ara.docx_analysis.visible_main._reader import Refusal, boolean, check

LEAVES = {
    "table": {"tblW", "jc", "tblInd", "tblLayout", "tblCellSpacing", "tblLook", "shd"},
    "row": {"gridBefore", "gridAfter", "trHeight", "wBefore", "wAfter", "jc"},
    "cell": {"gridSpan", "vMerge", "tcW", "shd", "vAlign", "textDirection"},
}
BOOLS = {
    "table": {"bidiVisual"},
    "row": {"cantSplit", "tblHeader", "hidden"},
    "cell": {"noWrap", "tcFitText", "hideMark"},
}
CONTAINERS = {
    "table": {"tblBorders", "tblCellMar"},
    "row": set(),
    "cell": {"tcBorders", "tcMar"},
}
EDGES = {"top", "left", "bottom", "right", "start", "end"}
BORDERS = EDGES | {"insideH", "insideV", "tl2br", "tr2bl"}


class Properties:
    def __init__(self, reader):
        self.r = reader

    def formatting_leaf(self, node):
        self.r.leaf(node)
        check(all(a.startswith(self.r.ns) for a in node.attrib))

    def composite(self, node):
        self.r.attrs(node)
        self.r.container(node)
        allowed = BORDERS if self.r.name(node).endswith("Borders") else EDGES
        seen = set()
        for child in node:
            name = self.r.name(child)
            check(name in allowed and name not in seen)
            seen.add(name)
            self.formatting_leaf(child)

    def table_style(self, node):
        raise Refusal("unresolved_table_style")

    def extended(self, node, kind):
        raise Refusal()

    def read(self, anchor, kind):
        if anchor is None:
            return
        node = self.r.nodes[anchor]
        try:
            self.r.attrs(node)
            self.r.container(node)
            seen = set()
            for child in node:
                name = self.r.name(child)
                check(name not in seen)
                seen.add(name)
                if kind == "table" and name == "tblStyle":
                    self.table_style(child)
                elif name in LEAVES[kind]:
                    self.formatting_leaf(child)
                elif name in BOOLS[kind]:
                    self.r.leaf(child)
                    self.r.attrs(child, {"val"})
                    value = boolean(self.r.attr(child, "val"))
                    if kind == "row" and name == "hidden" and value:
                        raise Refusal("unresolved_hidden_row")
                elif name in CONTAINERS[kind]:
                    self.composite(child)
                else:
                    self.extended(child, kind)
        except Refusal as exc:
            if exc.code in ("unresolved_table_style", "unresolved_hidden_row"):
                raise
            raise Refusal("unsupported_table_properties") from None
        self.r.event("metadata", "table_properties", node)
