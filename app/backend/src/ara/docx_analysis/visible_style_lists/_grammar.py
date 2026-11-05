"""Closed abstract pStyle admission; replacement bindings remain unproved."""

from ara.docx_analysis.visibility._grammar import boolean, check, identity
from ara.docx_analysis.visible_unlisted._grammar import Grammar as BaseGrammar
from ara.docx_analysis.visible_unlisted._grammar import hexadecimal, integer


class Grammar(BaseGrammar):
    def level(self, node):
        self.attrs(node, {"ilvl", "tplc", "tentative"}, {"ilvl"})
        level = integer(self.attr(node, "ilvl"), maximum=8)
        if self.attr(node, "tplc") is not None:
            hexadecimal(self.attr(node, "tplc"))
        if self.attr(node, "tentative") is not None:
            boolean(self.attr(node, "tentative"))
        for child in self.ordered(
            node,
            (
                "start",
                "numFmt",
                "lvlRestart",
                "pStyle",
                "isLgl",
                "suff",
                "lvlText",
                "lvlJc",
                "pPr",
                "rPr",
            ),
        ):
            name = self.name(child)
            if name == "pPr":
                self.paragraph(child)
            elif name == "rPr":
                self.properties(child, "rPr")
            elif name == "isLgl":
                self.leaf(child)
                self.attrs(child, {"val"})
                boolean(self.attr(child, "val"))
            elif name == "lvlText":
                self.leaf(child)
                self.attrs(child, {"val", "null"}, {"val"})
                if self.attr(child, "null") is not None:
                    boolean(self.attr(child, "null"))
            else:
                value = self.value(child)
                if name == "pStyle":
                    identity(value)
                elif name in {"start", "lvlRestart"}:
                    integer(value)
                elif name == "numFmt":
                    check(
                        value
                        in {
                            "decimal",
                            "bullet",
                            "none",
                            "upperRoman",
                            "lowerRoman",
                            "upperLetter",
                            "lowerLetter",
                        }
                    )
                elif name == "suff":
                    check(value in {"tab", "space", "nothing"})
                else:
                    check(value in {"left", "right", "center"})
                    check("purl.oclc.org" not in self.ns or value == "center")
        return level

    def number(self, node, definitions):
        for override in node:
            if self.name(override) == "lvlOverride":
                for level in override:
                    if self.name(level) == "lvl":
                        check(not any(self.name(n) == "pStyle" for n in level))
        return super().number(node, definitions)
