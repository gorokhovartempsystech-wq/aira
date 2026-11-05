"""Prove anchored raster metadata without inferring physical page layout."""

from ara.docx_analysis.visible_inline_images._grammar import Grammar as InlineGrammar
from ara.docx_analysis.visible_inline_images._grammar import boolean, integer, require

HORIZONTAL = {
    "margin",
    "page",
    "column",
    "character",
    "leftMargin",
    "rightMargin",
    "insideMargin",
    "outsideMargin",
}
VERTICAL = {
    "margin",
    "page",
    "paragraph",
    "line",
    "topMargin",
    "bottomMargin",
    "insideMargin",
    "outsideMargin",
}
WRAPS = {"wrapNone", "wrapSquare", "wrapTopAndBottom", "wrapTight", "wrapThrough"}
DISTANCES = {"distT", "distB", "distL", "distR"}
COORDINATE = 27273042316900


class Grammar(InlineGrammar):
    def position(self, node, horizontal):
        self.attrs(node, {"relativeFrom"}, {"relativeFrom"})
        require(node.get("relativeFrom") in (HORIZONTAL if horizontal else VERTICAL))
        self.container(node)
        require(len(node) == 1)
        child = node[0]
        self.attrs(child)
        require(len(child) == 0)
        text = (child.text or "").strip(" \t\r\n")
        if child.tag == self.wp + "align":
            choices = {"left", "right"} if horizontal else {"top", "bottom"}
            require(text in choices | {"center", "inside", "outside"})
        else:
            require(child.tag == self.wp + "posOffset")
            integer(text, -2147483648, 2147483647)

    def effect(self, node):
        self.coordinates(node, {"l", "t", "r", "b"}, -COORDINATE, COORDINATE)

    def polygon(self, node):
        self.attrs(node, {"edited"})
        if node.get("edited") is not None:
            boolean(node.get("edited"))
        self.container(node)
        require(len(node) >= 3 and node[0].tag == self.wp + "start")
        for index, child in enumerate(node):
            if index:
                require(child.tag == self.wp + "lineTo")
            self.coordinates(child, {"x", "y"}, -COORDINATE, COORDINATE)

    def wrap(self, node, kind, behind):
        if kind == "wrapNone":
            self.attrs(node)
            self.leaf(node)
            require(behind, "unsupported_floating_overlay")
            return
        polygon = kind in ("wrapTight", "wrapThrough")
        allowed = (
            {"distL", "distR"}
            if polygon
            else {"distT", "distB"}
            if kind == "wrapTopAndBottom"
            else DISTANCES
        )
        required = set() if kind == "wrapTopAndBottom" else {"wrapText"}
        self.attrs(node, allowed | required, required)
        for name in allowed:
            if node.get(name) is not None:
                integer(node.get(name), 0, 0xFFFFFFFF)
        if required:
            require(node.get("wrapText") in {"bothSides", "left", "right", "largest"})
        name = "wrapPolygon" if polygon else "effectExtent"
        children = self.sequence(node, ((self.wp + name, polygon),))
        for child in children.values():
            if polygon:
                self.polygon(child)
            else:
                self.effect(child)

    def drawing(self, node):
        self.attrs(node)
        anchor = self.sequence(node, ((self.wp + "anchor", True),))[self.wp + "anchor"]
        required = {"relativeHeight", "behindDoc", "locked", "layoutInCell", "allowOverlap"}
        self.attrs(anchor, required | DISTANCES | {"simplePos", "hidden"}, required)
        integer(anchor.get("relativeHeight"), 0, 0xFFFFFFFF)
        for name in DISTANCES:
            if anchor.get(name) is not None:
                integer(anchor.get(name), 0, 0xFFFFFFFF)
        flags = {}
        for name in ("behindDoc", "locked", "layoutInCell", "allowOverlap", "simplePos", "hidden"):
            if anchor.get(name) is not None:
                flags[name] = boolean(anchor.get(name))
        wrappers = [child for child in anchor if child.tag in {self.wp + n for n in WRAPS}]
        require(len(wrappers) == 1)
        wrapper = wrappers[0]
        children = self.sequence(
            anchor,
            (
                (self.wp + "simplePos", True),
                (self.wp + "positionH", True),
                (self.wp + "positionV", True),
                (self.wp + "extent", True),
                (self.wp + "effectExtent", False),
                (wrapper.tag, True),
                (self.wp + "docPr", True),
                (self.wp + "cNvGraphicFramePr", False),
                (self.a + "graphic", True),
            ),
        )
        self.coordinates(children[self.wp + "simplePos"], {"x", "y"}, -COORDINATE, COORDINATE)
        self.position(children[self.wp + "positionH"], True)
        self.position(children[self.wp + "positionV"], False)
        self.coordinates(children[self.wp + "extent"], {"cx", "cy"}, 1, COORDINATE)
        if self.wp + "effectExtent" in children:
            self.effect(children[self.wp + "effectExtent"])
        self.wrap(wrapper, wrapper.tag[len(self.wp) :], flags["behindDoc"])
        object_hidden = self.object_props(children[self.wp + "docPr"])
        if self.wp + "cNvGraphicFramePr" in children:
            self.frame_props(children[self.wp + "cNvGraphicFramePr"])
        picture_hidden = self.graphic(children[self.a + "graphic"])
        return flags.get("hidden", False) or object_hidden or picture_hidden
