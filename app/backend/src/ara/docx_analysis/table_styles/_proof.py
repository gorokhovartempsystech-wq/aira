"""All conditional branches must be neutral; no regional visibility guessing."""

import re
from dataclasses import dataclass

from ara.docx_analysis.visibility._grammar import (
    FORMATTING,
    PARAGRAPH,
    UI_BOOL,
    Grammar,
    Unsupported,
    boolean,
    check,
    decimal,
    identity,
)

from ._models import TableStyleRegion

REGIONS = {
    "wholeTable",
    "firstRow",
    "lastRow",
    "firstCol",
    "lastCol",
    "band1Vert",
    "band2Vert",
    "band1Horz",
    "band2Horz",
    "neCell",
    "nwCell",
    "seCell",
    "swCell",
}
LEAVES = {
    "rPr": FORMATTING,
    "pPr": PARAGRAPH,
    "tblPr": {
        "tblW",
        "jc",
        "tblInd",
        "tblLayout",
        "tblCellSpacing",
        "tblLook",
        "shd",
        "tblStyleRowBandSize",
        "tblStyleColBandSize",
    },
    "trPr": {"trHeight", "jc"},
    "tcPr": {"tcW", "shd", "vAlign", "textDirection"},
}
BOOLS = {
    "rPr": set(),
    "pPr": set(),
    "tblPr": {"bidiVisual"},
    "trPr": {"cantSplit", "tblHeader"},
    "tcPr": {"noWrap", "tcFitText", "hideMark"},
}
COMPOSITES = {
    "rPr": set(),
    "pPr": set(),
    "tblPr": {"tblBorders", "tblCellMar"},
    "trPr": set(),
    "tcPr": {"tcBorders", "tcMar"},
}
EDGES = {"top", "left", "bottom", "right", "start", "end"}
BORDERS = EDGES | {"insideH", "insideV", "tl2br", "tr2bl"}
UI = {"name", "aliases", "next", "link", "uiPriority", "rsid"} | UI_BOOL


@dataclass(frozen=True)
class Own:
    record: object
    parent: str | None = None
    regions: tuple = ()
    metadata: tuple = ()
    code: str | None = None


class Proof(Grammar):
    def format_leaf(self, node):
        self.leaf(node)
        check(all(a.startswith(self.ns) for a in node.attrib))

    def props(self, node, metadata):
        kind = self.name(node)
        self.attrs(node)
        metadata.append(self.anchors[node])
        for child in self.children(node, LEAVES[kind] | BOOLS[kind] | COMPOSITES[kind]):
            name = self.name(child)
            metadata.append(self.anchors[child])
            if name in LEAVES[kind]:
                self.format_leaf(child)
            elif name in BOOLS[kind]:
                self.leaf(child)
                self.attrs(child, {"val"})
                boolean(self.attr(child, "val"))
            else:
                self.attrs(child)
                for edge in self.children(child, BORDERS if name.endswith("Borders") else EDGES):
                    self.format_leaf(edge)
                    metadata.append(self.anchors[edge])

    def own(self, record, node):
        parent, regions, metadata, kinds = None, [], [], set()
        try:
            for child in self.children(
                node, set(LEAVES) | UI | {"basedOn", "tblStylePr"}, {"tblStylePr"}
            ):
                name = self.name(child)
                if name in LEAVES:
                    self.props(child, metadata)
                elif name == "tblStylePr":
                    self.attrs(child, {"type"}, {"type"})
                    kind = self.attr(child, "type")
                    check(kind in REGIONS and kind not in kinds)
                    kinds.add(kind)
                    for props in self.children(child, set(LEAVES)):
                        self.props(props, metadata)
                    regions.append(TableStyleRegion(kind, self.anchors[child]))
                else:
                    self.leaf(child)
                    self.attrs(child, {"val"}, () if name in UI_BOOL else {"val"})
                    value = self.attr(child, "val")
                    if name == "basedOn":
                        parent = identity(value)
                        continue
                    if name in UI_BOOL:
                        boolean(value)
                    elif name == "uiPriority":
                        decimal(value)
                    elif name == "rsid":
                        check(re.fullmatch(r"[0-9a-fA-F]{8}", value) is not None)
                    metadata.append(self.anchors[child])
        except Unsupported:
            return Own(record, code="unsupported_table_style")
        return Own(record, parent, tuple(regions), tuple(metadata))
