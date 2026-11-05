"""Contextual narrow Word grammar; unsupported main flows are never partially emitted."""

import re
from dataclasses import dataclass, field

from ara.docx_package.projection import SourceAnchor


class Unsupported(Exception):
    """No source details in a grammar refusal."""


@dataclass
class ParagraphPlan:
    node: object = field(repr=False)
    atoms: list = field(default_factory=list, repr=False)
    marker: object = field(default=None, repr=False)


FORMATTING = frozenset(
    (
        "b",
        "bCs",
        "i",
        "iCs",
        "u",
        "strike",
        "dstrike",
        "color",
        "highlight",
        "sz",
        "szCs",
        "vertAlign",
        "lang",
        "rFonts",
    )
)
PARAGRAPH_FORMATTING = frozenset(
    ("pStyle", "spacing", "ind", "jc", "outlineLvl", "keepNext", "keepLines", "pageBreakBefore")
)
MARKERS = frozenset(("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd"))


class Reader:
    def __init__(self, root, source):
        self.root = root
        self.namespace = root.tag.rsplit("}", 1)[0] + "}"
        self.anchors = {}
        stack = [(root, ())]
        while stack:
            node, path = stack.pop()
            self.anchors[node] = SourceAnchor(source.sha256, source.main_part, path)
            stack.extend((child, path + (i,)) for i, child in enumerate(node))
        self.body = next(n for n in root if self.name(n) == "body")
        self.events = []

    def name(self, node):
        return node.tag[len(self.namespace) :] if node.tag.startswith(self.namespace) else ""

    def attr(self, node, name):
        return node.get(self.namespace + name)

    def check(self, condition):
        if not condition:
            raise Unsupported()

    def containers(self, node):
        self.check(not (node.text or "").strip())
        self.check(all(not (child.tail or "").strip() for child in node))

    def leaf(self, node, *, text=False):
        self.check(len(node) == 0)
        if not text:
            self.check(not (node.text or "").strip())

    def event(self, status, code, node):
        self.events.append((status, code, self.anchors[node]))

    def revision(self, node):
        identity = self.attr(node, "id")
        self.check(identity is not None and re.fullmatch(r"[+-]?[0-9]{1,20}", identity) is not None)

    def properties(self, node, kind, plan=None):
        self.containers(node)
        self.event("metadata", "supported_properties", node)
        seen = set()
        revision_seen = False
        for child in node:
            name = self.name(child)
            self.check(name not in seen)
            seen.add(name)
            if self.property_history(child, kind):
                continue
            if kind == "pPr" and name == "numPr":
                self.containers(child)
                nums = [self.name(n) for n in child]
                self.check(len(set(nums)) == len(nums) and set(nums) <= {"ilvl", "numId"})
                for n in child:
                    self.leaf(n)
            elif kind == "pPr" and name == "rPr":
                self.properties(child, "mark", plan)
            elif kind == "mark" and name in ("ins", "del"):
                self.check(not revision_seen)
                revision_seen = True
                self.revision(child)
                self.leaf(child)
                self.event(
                    "excluded" if name == "del" else "metadata",
                    "deleted_boundary" if name == "del" else "inserted_boundary",
                    child,
                )
                if name == "del":
                    plan.marker = child
            else:
                allowed = PARAGRAPH_FORMATTING if kind == "pPr" else FORMATTING
                self.check(name in allowed)
                self.leaf(child)

    def property_history(self, node, kind):
        # The original main profile never interprets property-history markup.
        return False

    def inline(self, node, plan, context, in_link=False):
        self.containers(node)
        for index, child in enumerate(node):
            name = self.name(child)
            if context == "p" and name == "pPr":
                self.check(index == 0)
                self.properties(child, "pPr", plan)
            elif name == "r":
                self.run(child, plan)
            elif name == "hyperlink":
                self.check(not in_link)
                self.inline(child, plan, "hyperlink", True)
            elif name in ("ins", "del"):
                self.revision(child)
                if name == "del":
                    self.event("excluded", "deleted_content", child)
                else:
                    self.event("metadata", "inserted_content", child)
                    self.inline(child, plan, "ins", in_link)
            elif name in MARKERS:
                self.leaf(child)
                self.event(
                    "metadata" if name.startswith("bookmark") else "excluded",
                    "bookmark" if name.startswith("bookmark") else "comments_policy",
                    child,
                )
            else:
                raise Unsupported()

    def run(self, node, plan):
        self.containers(node)
        for index, child in enumerate(node):
            name = self.name(child)
            if name == "rPr":
                self.check(index == 0)
                self.properties(child, "rPr")
            elif name in ("t", "tab", "br", "cr"):
                self.leaf(child, text=name == "t")
                if name == "br":
                    self.check(self.attr(child, "type") in (None, "textWrapping", "page", "column"))
                kind = "text" if name == "t" else "tab" if name == "tab" else "break"
                text = (child.text or "") if name == "t" else "\t" if name == "tab" else "\n"
                if text:
                    plan.atoms.append((kind, child, node, text))
            elif name == "commentReference":
                self.leaf(child)
                self.event("excluded", "comments_policy", child)
            else:
                raise Unsupported()

    def plans(self):
        self.containers(self.root)
        self.check(sum(self.name(n) == "background" for n in self.root) <= 1)
        for child in self.root:
            if child is not self.body:
                self.check(self.name(child) == "background")
                self.leaf(child)
        self.containers(self.body)
        paragraphs = []
        for index, child in enumerate(self.body):
            name = self.name(child)
            if name == "sectPr":
                self.check(index == len(self.body) - 1)
                self.containers(child)
                names = [self.name(n) for n in child]
                self.check(
                    len(set(names)) == len(names)
                    and set(names) <= {"pgSz", "pgMar", "cols", "docGrid"}
                )
                for n in child:
                    self.leaf(n)
            else:
                self.check(name == "p")
                plan = ParagraphPlan(child)
                self.inline(child, plan, "p")
                paragraphs.append(plan)
        self.check(not paragraphs or paragraphs[-1].marker is None)
        return paragraphs
