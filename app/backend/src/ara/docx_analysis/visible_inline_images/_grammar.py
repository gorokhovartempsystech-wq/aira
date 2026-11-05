"""Closed inline-picture grammar; foreign extensions never become hidden text."""

import re

from ara.docx_analysis.visible_main._reader import Refusal


def require(value, code="unsupported_inline_drawing"):
    if not value:
        raise Refusal(code)


def integer(value, low, high):
    require(type(value) is str and re.fullmatch(r"[+-]?[0-9]{1,20}", value) is not None)
    require(low <= int(value) <= high)


def boolean(value):
    require(value in ("true", "false", "0", "1"))
    return value in ("true", "1")


class Grammar:
    def __init__(self, reader, media):
        self.r, self.media = reader, media
        self.strict = "purl.oclc.org" in reader.ns
        base = (
            "http://purl.oclc.org/ooxml/drawingml/"
            if self.strict
            else "http://schemas.openxmlformats.org/drawingml/2006/"
        )
        self.wp, self.a, self.pic = (
            "{" + base + n + "}" for n in ("wordprocessingDrawing", "main", "picture")
        )

    def attrs(self, node, allowed=(), required=()):
        require(set(node.attrib) <= set(allowed) and set(required) <= set(node.attrib))

    def container(self, node):
        require(not (node.text or "").strip(" \t\r\n"))
        require(all(not (child.tail or "").strip(" \t\r\n") for child in node))

    def leaf(self, node):
        self.container(node)
        require(len(node) == 0)

    def sequence(self, node, specs):
        self.container(node)
        i, result = 0, {}
        for tag, required in specs:
            if i < len(node) and node[i].tag == tag:
                result[tag] = node[i]
                i += 1
            else:
                require(not required)
        require(i == len(node))
        return result

    def coordinates(self, node, names, low, high):
        self.attrs(node, names, names)
        self.leaf(node)
        for name in names:
            integer(node.get(name), low, high)

    def object_props(self, node):
        self.attrs(node, {"id", "name", "descr", "title", "hidden"}, {"id", "name"})
        self.leaf(node)
        integer(node.get("id"), 0, 0xFFFFFFFF)
        require(
            not node.get("descr") and not node.get("title"), "unsupported_image_alternative_text"
        )
        return boolean(node.get("hidden")) if node.get("hidden") is not None else False

    def locks(self, node, picture=False):
        names = {"noGrp", "noDrilldown", "noSelect", "noChangeAspect", "noMove", "noResize"}
        if picture:
            names |= {
                "noRot",
                "noChangeArrowheads",
                "noEditPoints",
                "noAdjustHandles",
                "noChangeShapeType",
                "noCrop",
            }
        self.attrs(node, names)
        self.leaf(node)
        for value in node.attrib.values():
            boolean(value)

    def frame_props(self, node):
        self.attrs(node)
        children = self.sequence(node, ((self.a + "graphicFrameLocks", False),))
        for child in children.values():
            self.locks(child)

    def picture_props(self, node):
        self.attrs(node, {"preferRelativeResize"})
        if node.get("preferRelativeResize") is not None:
            boolean(node.get("preferRelativeResize"))
        children = self.sequence(node, ((self.a + "picLocks", False),))
        for child in children.values():
            self.locks(child, picture=True)

    def rectangle(self, node):
        self.attrs(node, {"l", "t", "r", "b"})
        self.leaf(node)
        for value in node.attrib.values():
            if self.strict:
                require(re.fullmatch(r"[+-]?[0-9]{1,7}(?:\.[0-9]{1,6})?%", value) is not None)
            else:
                integer(value, -2147483648, 2147483647)

    def fill(self, node):
        self.attrs(node, {"dpi", "rotWithShape"})
        if node.get("dpi") is not None:
            integer(node.get("dpi"), 0, 0xFFFFFFFF)
        if node.get("rotWithShape") is not None:
            boolean(node.get("rotWithShape"))
        children = self.sequence(
            node, ((self.a + "blip", True), (self.a + "srcRect", False), (self.a + "stretch", True))
        )
        blip = children[self.a + "blip"]
        rid = "{" + self.r.rel_ns + "}embed"
        self.attrs(blip, {rid, "cstate"}, {rid})
        self.leaf(blip)
        require(blip.get("cstate") in (None, "none", "email", "screen", "print", "hqprint"))
        if self.a + "srcRect" in children:
            self.rectangle(children[self.a + "srcRect"])
        stretch = children[self.a + "stretch"]
        self.attrs(stretch)
        rect = self.sequence(stretch, ((self.a + "fillRect", True),))[self.a + "fillRect"]
        self.rectangle(rect)
        self.media.use(self.r, blip, blip.get(rid))

    def shape(self, node):
        self.attrs(node)
        children = self.sequence(node, ((self.a + "xfrm", False), (self.a + "prstGeom", True)))
        if self.a + "xfrm" in children:
            transform = children[self.a + "xfrm"]
            self.attrs(transform, {"rot", "flipH", "flipV"})
            if transform.get("rot") is not None:
                integer(transform.get("rot"), -2147483648, 2147483647)
            for name in ("flipH", "flipV"):
                if transform.get(name) is not None:
                    boolean(transform.get(name))
            parts = self.sequence(transform, ((self.a + "off", False), (self.a + "ext", False)))
            if self.a + "off" in parts:
                self.coordinates(parts[self.a + "off"], {"x", "y"}, -27273042316900, 27273042316900)
            if self.a + "ext" in parts:
                self.coordinates(parts[self.a + "ext"], {"cx", "cy"}, 1, 27273042316900)
        geometry = children[self.a + "prstGeom"]
        self.attrs(geometry, {"prst"}, {"prst"})
        require(geometry.get("prst") == "rect")
        for child in self.sequence(geometry, ((self.a + "avLst", False),)).values():
            self.attrs(child)
            self.leaf(child)

    def picture(self, node):
        self.attrs(node)
        children = self.sequence(
            node,
            (
                (self.pic + "nvPicPr", True),
                (self.pic + "blipFill", True),
                (self.pic + "spPr", True),
            ),
        )
        nonvisual = children[self.pic + "nvPicPr"]
        self.attrs(nonvisual)
        props = self.sequence(
            nonvisual, ((self.pic + "cNvPr", True), (self.pic + "cNvPicPr", True))
        )
        hidden = self.object_props(props[self.pic + "cNvPr"])
        self.picture_props(props[self.pic + "cNvPicPr"])
        self.fill(children[self.pic + "blipFill"])
        self.shape(children[self.pic + "spPr"])
        return hidden

    def drawing(self, node):
        self.attrs(node)
        inline = self.sequence(node, ((self.wp + "inline", True),))[self.wp + "inline"]
        self.attrs(inline, {"distT", "distB", "distL", "distR"})
        for value in inline.attrib.values():
            integer(value, 0, 0xFFFFFFFF)
        children = self.sequence(
            inline,
            (
                (self.wp + "extent", True),
                (self.wp + "effectExtent", False),
                (self.wp + "docPr", True),
                (self.wp + "cNvGraphicFramePr", False),
                (self.a + "graphic", True),
            ),
        )
        self.coordinates(children[self.wp + "extent"], {"cx", "cy"}, 1, 27273042316900)
        if self.wp + "effectExtent" in children:
            self.coordinates(
                children[self.wp + "effectExtent"],
                {"l", "t", "r", "b"},
                -27273042316900,
                27273042316900,
            )
        hidden = self.object_props(children[self.wp + "docPr"])
        if self.wp + "cNvGraphicFramePr" in children:
            self.frame_props(children[self.wp + "cNvGraphicFramePr"])
        # Do not short-circuit the proof for a hidden object.
        picture_hidden = self.graphic(children[self.a + "graphic"])
        return hidden or picture_hidden

    def graphic(self, graphic):
        self.attrs(graphic)
        data = self.sequence(graphic, ((self.a + "graphicData", True),))[self.a + "graphicData"]
        self.attrs(data, {"uri"}, {"uri"})
        require(data.get("uri") == self.pic[1:-1])
        picture = self.sequence(data, ((self.pic + "pic", True),))[self.pic + "pic"]
        return self.picture(picture)
