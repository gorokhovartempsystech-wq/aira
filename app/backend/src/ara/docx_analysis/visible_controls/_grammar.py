"""Validate control metadata without treating it as text or current-run formatting."""

import re

from ara.docx_analysis.visible_main._reader import Refusal, boolean, check


class Grammar:
    def __init__(self, reader):
        self.r = reader

    def string(self, node):
        self.r.attrs(node, {"val"}, {"val"})
        self.r.leaf(node)

    def properties(self, node):
        r, seen = self.r, set()
        r.attrs(node)
        r.container(node)
        for child in node:
            name = r.name(child)
            check(name not in seen)
            seen.add(name)
            if name == "rPr":
                # The saved children carry their own current properties. These describe input.
                r.properties(child, "rPr")
            elif name in ("alias", "tag", "id", "label", "tabIndex"):
                self.string(child)
                if name in ("id", "label", "tabIndex"):
                    pattern = r"[+]?[0-9]{1,20}" if name == "tabIndex" else r"[+-]?[0-9]{1,20}"
                    check(re.fullmatch(pattern, r.attr(child, "val")) is not None)
            elif name == "lock":
                r.attrs(child, {"val"})
                r.leaf(child)
                check(
                    r.attr(child, "val")
                    in (None, "unlocked", "sdtLocked", "contentLocked", "sdtContentLocked")
                )
            elif name in ("temporary", "showingPlcHdr"):
                r.attrs(child, {"val"})
                r.leaf(child)
                enabled = boolean(r.attr(child, "val"))
                if enabled and name == "showingPlcHdr":
                    raise Refusal("unsupported_placeholder_control")
            elif name == "placeholder":
                r.attrs(child)
                r.container(child)
                check(len(child) == 1 and r.name(child[0]) == "docPart")
                self.string(child[0])
            elif name == "richText":
                r.attrs(child)
                r.leaf(child)
            else:
                self.extended_property(child)
        r.event("metadata", "control_properties", node)

    def extended_property(self, node):
        raise Refusal("unsupported_control_properties")

    def control_code(self):
        return "rich_text_control"

    def end_properties(self, node):
        r = self.r
        r.attrs(node)
        r.container(node)
        for child in node:
            check(r.name(child) == "rPr")
            r.properties(child, "rPr")
        r.event("metadata", "control_end_properties", node)

    def content(self, node):
        r, last, result = self.r, -1, None
        r.attrs(node)
        r.container(node)
        order = {"sdtPr": 0, "sdtEndPr": 1, "sdtContent": 2}
        for child in node:
            name = r.name(child)
            check(name in order and order[name] > last)
            last = order[name]
            if name == "sdtPr":
                self.properties(child)
            elif name == "sdtEndPr":
                self.end_properties(child)
            else:
                r.attrs(child)
                r.container(child)
                result = child
        r.event("metadata", self.control_code(), node)
        if result is None or not len(result):
            r.event("metadata", "empty_control", node)
        return result
