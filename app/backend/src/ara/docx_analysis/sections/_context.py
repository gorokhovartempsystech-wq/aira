"""Current section identity uses actual parents, never name-only flattening."""

import re

from ara.docx_analysis.tables._parse import word_name
from ara.docx_package.projection import SourceAnchor

from ._models import Section, SectionHistory, budget, require
from ._resolve import References, boolean

METADATA = {
    "footnotePr",
    "endnotePr",
    "type",
    "pgSz",
    "pgMar",
    "paperSrc",
    "pgBorders",
    "lnNumType",
    "pgNumType",
    "cols",
    "formProt",
    "vAlign",
    "noEndnote",
    "textDirection",
    "bidi",
    "rtlGutter",
    "docGrid",
    "printerSettings",
}
HISTORIES = {"sectPrChange": ("sectPr", "section"), "pPrChange": ("pPr", "paragraph")}
RELEVANT = {"sectPr", "headerReference", "footerReference", "titlePg"} | set(HISTORIES)


class Context:
    def __init__(self, root, source, limits):
        self.ns = root.tag.rpartition("}")[0] + "}"
        self.body = next(n for n in root if n.tag == self.ns + "body")
        self.anchors, self.parents = {}, {}
        stack = [(root, (), None)]
        while stack:
            node, path, parent = stack.pop()
            self.anchors[node] = self.anchor_for(node, path, source.sha256, source.main_part)
            self.parents[node] = parent
            stack.extend((n, path + (i,), node) for i, n in reversed(list(enumerate(node))))
        self.sections, self.histories, self.current = [], [], set()
        self.references = References(source, self.ns)
        stack = [root]
        while stack:
            node = stack.pop()
            name = word_name(node.tag)
            if name in RELEVANT:
                self.check(node.tag == self.ns + name, node, "unsupported_section_context")
                if name in HISTORIES:
                    self.history(node, name)
                    continue
                if name == "sectPr":
                    self.section(node)
                else:
                    self.check(
                        self.parents[node] in self.current, node, "unsupported_section_context"
                    )
            stack.extend(reversed(node))
        if not self.sections or self.sections[-1].paragraph_anchor is not None:
            self.sections.append(Section(len(self.sections), None, None, False, (), ()))
        budget(len(self.sections), limits.max_sections)

    def anchor_for(self, node, path, sha, part):
        return SourceAnchor(sha, part, path)

    def check(self, condition, node, code="invalid_section_markup"):
        require(condition, code, self.anchors[node])

    def name(self, node):
        return node.tag[len(self.ns) :] if node.tag.startswith(self.ns) else ""

    def container(self, node):
        self.check(
            not (node.text or "").strip()
            and not (node.tail or "").strip()
            and all(not (n.tail or "").strip() for n in node),
            node,
        )

    def section_attrs(self, node):
        self.check(
            set(node.attrib) <= {self.ns + n for n in ("rsidR", "rsidRPr", "rsidSect", "rsidDel")}
            and all(re.fullmatch(r"[0-9a-fA-F]{8}", v) is not None for v in node.attrib.values()),
            node,
        )

    def body_properties(self, node):
        paragraph = self.parents[node]
        self.check(
            self.name(node) == "pPr"
            and paragraph is not None
            and self.name(paragraph) == "p"
            and self.parents[paragraph] is self.body,
            node,
            "unsupported_section_context",
        )
        self.check(
            not node.attrib
            and len(paragraph) > 0
            and paragraph[0] is node
            and sum(self.name(n) == "pPr" for n in paragraph) == 1,
            node,
        )
        self.container(node)
        return paragraph

    def section(self, node):
        parent = self.parents[node]
        paragraph = None
        if parent is self.body:
            self.check(self.body[-1] is node, node)
        else:
            self.check(parent is not None, node, "unsupported_section_context")
            paragraph = self.body_properties(parent)
            end = len(parent) - (1 if self.name(parent[-1]) == "pPrChange" else 0)
            self.check(end > 0 and parent[end - 1] is node, node)
            for mark in parent:
                if word_name(mark.tag) == "rPr":
                    self.check(
                        not any(
                            word_name(n.tag) in {"ins", "del", "moveFrom", "moveTo"} for n in mark
                        ),
                        node,
                        "unresolved_section_revision",
                    )
        self.section_attrs(node)
        self.container(node)
        references, seen, first, after_refs = [], set(), False, False
        for child in node:
            name = self.name(child)
            self.check(
                name
                in METADATA | {"headerReference", "footerReference", "titlePg", "sectPrChange"},
                child,
            )
            if name in ("headerReference", "footerReference"):
                self.check(not after_refs, child)
                ref = self.references.read(
                    child, name.removesuffix("Reference"), self.anchors[child]
                )
                key = (ref.kind, ref.variant)
                self.check(key not in seen, child)
                seen.add(key)
                references.append(ref)
            else:
                after_refs = True
                self.check(name not in seen, child)
                seen.add(name)
                if name == "titlePg":
                    first = boolean(child, self.ns, "invalid_section_markup", self.anchors[child])
        self.current.add(node)
        self.sections.append(
            Section(
                len(self.sections),
                self.anchors[node],
                self.anchors[paragraph] if paragraph is not None else None,
                first,
                tuple(references),
                (),
            )
        )

    def history(self, node, name):
        owner = self.parents[node]
        expected, kind = HISTORIES[name]
        if expected == "sectPr":
            self.check(owner in self.current, node, "unsupported_section_context")
        else:
            self.check(owner is not None, node, "unsupported_section_context")
            self.body_properties(owner)
        code = "invalid_section_history"
        identity = node.get(self.ns + "id")
        self.check(owner[-1] is node and sum(self.name(n) == name for n in owner) == 1, node, code)
        self.check(
            set(node.attrib) <= {self.ns + n for n in ("id", "author", "date")}
            and identity is not None
            and re.fullmatch(r"[+-]?[0-9]{1,20}", identity) is not None,
            node,
            code,
        )
        self.check(
            len(node) == 1
            and not (node.text or "").strip()
            and not (node.tail or "").strip()
            and node[0].tag == self.ns + expected,
            node,
            code,
        )
        previous = node[0]
        self.container(previous)
        if expected == "sectPr":
            self.section_attrs(previous)
        else:
            self.check(not previous.attrib, node, code)
        self.histories.append(
            SectionHistory(kind, self.anchors[node], self.anchors[owner], self.anchors[previous])
        )
