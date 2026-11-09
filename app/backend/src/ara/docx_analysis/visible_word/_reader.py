"""Word layout metadata with retained-text and original-coordinate checks."""

import re

from ara.docx_analysis.visible_main._reader import boolean, check
from ara.docx_analysis.visible_style_lists._reader import ListReader

from ._atoms import literal_math, symbol
from ._controls import Grammar
from ._layout import borders, positional_tab
from ._tabs import tabs


class Reader(ListReader):
    def extended_inline(self, child, paragraph, *, in_link, top):
        math_ns = (
            "http://purl.oclc.org/ooxml/officeDocument/math"
            if "purl.oclc.org" in self.ns
            else "http://schemas.openxmlformats.org/officeDocument/2006/math"
        )
        if child.tag == "{" + math_ns + "}oMath":
            literal_math(self, child, paragraph)
            return
        if self.name(child) == "proofErr":
            self.attrs(child, {"type"}, {"type"})
            self.leaf(child)
            check(self.attr(child, "type") in ("spellStart", "spellEnd", "gramStart", "gramEnd"))
            self.event("metadata", "proofing_marker", child)
            return
        return super().extended_inline(child, paragraph, in_link=in_link, top=top)

    def extended_run(self, child, plan):
        name = self.name(child)
        if name == "sym":
            plan.atoms.append(("symbol", child, symbol(self, child)))
            return
        if name in ("softHyphen", "noBreakHyphen"):
            self.attrs(child)
            self.leaf(child)
            if name == "softHyphen":
                self.event("metadata", "optional_hyphen", child)
            else:
                plan.atoms.append(("nonbreaking_hyphen", child, "\u2011"))
            return
        if name == "ptab":
            positional_tab(self, child)
            plan.atoms.append(("tab", child, "\t"))
            return
        if self.name(child) == "lastRenderedPageBreak":
            self.attrs(child)
            self.leaf(child)
            self.event("metadata", "cached_page_boundary", child)
            return
        return super().extended_run(child, plan)

    def continuation(self, cell):
        # Empty merged continuations may retain paragraph-mark formatting.
        # No text, fields, numbering, nested controls or hidden runs are discarded.
        for block in cell.blocks:
            node = self.nodes[block.anchor]
            check(block.kind == "paragraph")
            self.rsids(node, paragraph=True)
            self.container(node)
            check(len(node) <= 1)
            for prop in node:
                check(self.name(prop) == "pPr")
                self.attrs(prop)
                self.container(prop)
                check(len(prop) <= 1)
                for mark in prop:
                    check(self.name(mark) == "rPr")
                    self.properties(mark, "mark")
        self.event("excluded", "merged_cell_continuation", self.nodes[cell.anchor])

    def grammar_type(self):
        return Grammar

    def formatting_property(self, node, kind):
        if kind == "pPr" and self.name(node) == "pBdr":
            borders(self, node, check)
            return
        if kind == "pPr" and self.name(node) == "shd":
            self.leaf(node)
            self.attrs(node, {"val", "color", "fill", "themeFill"}, {"val"})
            check(self.attr(node, "val") in ("clear", "nil", "solid"))
            for key in ("color", "fill"):
                value = self.attr(node, key)
                check(value in (None, "auto") or re.fullmatch(r"[0-9a-fA-F]{6}", value) is not None)
            check(
                self.attr(node, "themeFill")
                in (
                    None,
                    "background1",
                    "background2",
                    "text1",
                    "text2",
                    "dark1",
                    "dark2",
                    "light1",
                    "light2",
                    "accent1",
                    "accent2",
                    "accent3",
                    "accent4",
                    "accent5",
                    "accent6",
                    "hyperlink",
                    "followedHyperlink",
                    "none",
                )
            )
            return
        if kind == "mark" and self.name(node) == "rStyle":
            self.selector(node)
            style = self.lists.styles.get(self.attr(node, "val"))
            check(
                style is not None and style.style_type == "character" and style.status == "resolved"
            )
            check(
                all(
                    getattr(style.properties, key).value is not True
                    for key in ("vanish", "spec_vanish", "web_hidden")
                )
            )
            return
        if kind == "pPr" and self.name(node) == "tabs":
            tabs(self, node, require=check)
            return
        if kind != "pPr" and self.name(node) in {"kern", "spacing", "noProof"}:
            self.leaf(node)
            self.attrs(node, {"val"}, () if self.name(node) == "noProof" else {"val"})
            value = self.attr(node, "val")
            if self.name(node) == "noProof":
                boolean(value)
            else:
                check(re.fullmatch(r"[+-]?[0-9]{1,10}", value) is not None)
                check(-(2**31) <= int(value) < 2**31)
                if self.name(node) == "kern":
                    check(int(value) >= 0)
            return
        if kind == "pPr" and self.name(node) == "contextualSpacing":
            check(not len(node) and not (node.text or "").strip(" \t\r\n"))
            self.attrs(node, {"val"})
            boolean(self.attr(node, "val"))
            return
        return super().formatting_property(node, kind)
