"""Independent retained-content grammar; visibility never bypasses syntax checks."""

import re
from dataclasses import dataclass, field

from ara.docx_analysis.visibility import VisibilityProperties, VisibilityValue
from ara.docx_analysis.visibility._grammar import FORMATTING, PARAGRAPH
from ara.docx_analysis.visibility._models import absent
from ara.docx_package.projection import SourceAnchor

from ._models import budget

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
VISIBILITY = ("vanish", "specVanish", "webHidden")


class Refusal(Exception):
    def __init__(self, code="unsupported_main_flow"):
        self.code = code
        super().__init__(code)


def check(value):
    if not value:
        raise Refusal()


def boolean(value):
    check(value in (None, "true", "1", "on", "false", "0", "off"))
    return value in (None, "true", "1", "on")


@dataclass
class Run:
    node: object = field(repr=False)
    selector: object = field(default=None, repr=False)
    properties: VisibilityProperties = field(default_factory=absent, repr=False)
    atoms: list = field(default_factory=list, repr=False)


@dataclass
class Paragraph:
    node: object = field(repr=False)
    selector: object = field(default=None, repr=False)
    mark: VisibilityProperties = field(default_factory=absent, repr=False)
    runs: list = field(default_factory=list, repr=False)


class Reader:
    def __init__(self, root, source, limits):
        self.root, self.source, self.limits = root, source, limits
        self.ns = root.tag.rpartition("}")[0] + "}"
        self.rel_ns = (
            "http://purl.oclc.org/ooxml/officeDocument/relationships"
            if "purl.oclc.org" in self.ns
            else "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        )
        self.links = {
            r.relationship_id: r for r in source.relationships if r.source_part == source.main_part
        }
        self.anchors = {}
        stack = [(root, ())]
        while stack:
            node, path = stack.pop()
            self.anchors[node] = SourceAnchor(source.sha256, source.main_part, path)
            stack.extend((n, path + (i,)) for i, n in enumerate(node))
        self.body = next(n for n in root if n.tag == self.ns + "body")
        self.events = []

    def name(self, node):
        return node.tag[len(self.ns) :] if node.tag.startswith(self.ns) else ""

    def attr(self, node, name):
        return node.get(self.ns + name)

    def attrs(self, node, allowed=(), required=()):
        check(set(node.attrib) <= {self.ns + n for n in allowed})
        check(all(self.ns + n in node.attrib for n in required))

    def container(self, node):
        check(not (node.text or "").strip())
        check(all(not (n.tail or "").strip() for n in node))

    def leaf(self, node, text=False):
        check(not len(node) and (text or not (node.text or "").strip()))

    def event(self, status, code, node):
        budget(len(self.events) + 1, self.limits.max_coverage_items)
        self.events.append((status, code, self.anchors[node]))

    def revision(self, node):
        self.attrs(node, {"id", "author", "date"}, {"id"})
        check(re.fullmatch(r"[+-]?[0-9]{1,20}", self.attr(node, "id")) is not None)

    def rsids(self, node, paragraph=False):
        names = {"rsidR", "rsidRPr", "rsidDel"}
        if paragraph:
            names |= {"rsidRDefault", "rsidP"}
        self.attrs(node, names)
        check(all(re.fullmatch(r"[0-9a-fA-F]{8}", v) is not None for v in node.attrib.values()))

    def selector(self, node):
        self.leaf(node)
        self.attrs(node, {"val"}, {"val"})
        check(1 <= len(self.attr(node, "val")) <= 253)

    def properties(self, node, kind, paragraph=None):
        self.attrs(node)
        self.container(node)
        self.event("metadata", "supported_properties", node)
        seen, selector, values = set(), None, {}
        old_kind = "pPr" if kind == "pPr" else "rPr"
        for child in node:
            name = self.name(child)
            check(name not in seen)
            seen.add(name)
            if name == old_kind + "Change":
                self.revision(child)
                self.container(child)
                check(len(child) == 1 and self.name(child[0]) == old_kind)
                self.event("excluded", "historical_properties", child)
            elif kind == "pPr" and name == "rPr":
                _, paragraph.mark = self.properties(child, "mark")
            elif name == ("pStyle" if kind == "pPr" else "rStyle") and kind != "mark":
                self.selector(child)
                selector = child
            elif kind != "pPr" and name in VISIBILITY:
                self.leaf(child)
                self.attrs(child, {"val"})
                values[name] = VisibilityValue(
                    boolean(self.attr(child, "val")), self.anchors[child]
                )
            elif kind == "mark" and name == "ins":
                self.revision(child)
                self.leaf(child)
                self.event("metadata", "inserted_boundary", child)
            else:
                check(name in (PARAGRAPH if kind == "pPr" else FORMATTING))
                self.leaf(child)
                check(all(a.startswith(self.ns) for a in child.attrib))
        return selector, VisibilityProperties(
            *(values.get(n, VisibilityValue(None, None)) for n in VISIBILITY)
        )

    def run(self, node):
        self.rsids(node)
        self.container(node)
        plan = Run(node)
        for i, child in enumerate(node):
            name = self.name(child)
            if name == "rPr":
                check(i == 0)
                plan.selector, plan.properties = self.properties(child, "rPr")
            elif name in ("t", "tab", "br", "cr"):
                self.leaf(child, text=name == "t")
                if name == "t":
                    check(set(child.attrib) <= {XML_SPACE})
                    check(child.get(XML_SPACE) in (None, "preserve", "default"))
                elif name == "br":
                    self.attrs(child, {"type", "clear"})
                    check(self.attr(child, "type") in (None, "textWrapping", "page", "column"))
                    check(self.attr(child, "clear") in (None, "none", "left", "right", "all"))
                else:
                    self.attrs(child)
                kind = "text" if name == "t" else "tab" if name == "tab" else "break"
                text = (child.text or "") if name == "t" else "\t" if name == "tab" else "\n"
                if text:
                    plan.atoms.append((kind, child, text))
            elif name == "commentReference":
                self.marker(child)
            else:
                raise Refusal()
        return plan

    def marker(self, node):
        name = self.name(node)
        bookmark = name.startswith("bookmark")
        start = name == "bookmarkStart"
        self.attrs(node, {"id", "name"} if start else {"id"}, {"id", "name"} if start else {"id"})
        self.leaf(node)
        check(re.fullmatch(r"[+-]?[0-9]{1,20}", self.attr(node, "id")) is not None)
        if start:
            check(bool(self.attr(node, "name")))
        self.event(
            "metadata" if bookmark else "excluded",
            "bookmark" if bookmark else "comments_policy",
            node,
        )

    def hyperlink(self, node):
        rid = "{" + self.rel_ns + "}id"
        allowed = {self.ns + n for n in ("anchor", "docLocation", "tooltip", "tgtFrame", "history")}
        check(set(node.attrib) <= allowed | {rid})
        if self.attr(node, "history") is not None:
            boolean(self.attr(node, "history"))
        identity = node.get(rid)
        if identity is None:
            check(bool(self.attr(node, "anchor")))
        else:
            link = self.links.get(identity)
            check(
                bool(identity)
                and link is not None
                and link.relationship_type == self.rel_ns + "/hyperlink"
            )

    def inline(self, node, paragraph, *, in_link=False, top=False):
        self.container(node)
        for i, child in enumerate(node):
            name = self.name(child)
            if name == "pPr" and top:
                check(i == 0)
                paragraph.selector, _ = self.properties(child, "pPr", paragraph)
            elif name == "r":
                paragraph.runs.append(self.run(child))
            elif name == "hyperlink":
                check(not in_link)
                self.hyperlink(child)
                self.inline(child, paragraph, in_link=True)
            elif name in ("ins", "del"):
                self.revision(child)
                if name == "del":
                    self.event("excluded", "deleted_content", child)
                else:
                    self.event("metadata", "inserted_content", child)
                    self.inline(child, paragraph, in_link=in_link)
            elif name in ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd"):
                self.marker(child)
            else:
                raise Refusal()

    def plans(self):
        self.attrs(self.root)
        self.container(self.root)
        check(len(self.root) == 1 and self.root[0] is self.body)
        self.attrs(self.body)
        self.container(self.body)
        result = []
        for i, node in enumerate(self.body):
            name = self.name(node)
            if name == "sectPr":
                check(i == len(self.body) - 1)
                self.attrs(node)
                self.container(node)
                seen = set()
                for child in node:
                    kind = self.name(child)
                    check(kind in {"pgSz", "pgMar", "cols", "docGrid"} and kind not in seen)
                    seen.add(kind)
                    self.leaf(child)
                    check(all(a.startswith(self.ns) for a in child.attrib))
            else:
                check(name == "p")
                self.rsids(node, paragraph=True)
                p = Paragraph(node)
                self.inline(node, p, top=True)
                result.append(p)
        return result
