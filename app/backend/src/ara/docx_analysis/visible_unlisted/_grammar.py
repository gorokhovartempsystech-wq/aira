"""Closed unbound numbering definitions; no active counter or label interpretation."""

import re

from ara.docx_analysis.visibility._grammar import Grammar as StyleGrammar
from ara.docx_analysis.visibility._grammar import boolean, check


def integer(value, *, maximum=2147483647, signed=False, positive=False):
    check(value is not None and re.fullmatch(r"[+-]?[0-9]+" if signed else r"[+]?[0-9]+", value))
    digits = value.lstrip("+-").lstrip("0") or "0"
    check(len(digits) < 10 or (len(digits) == 10 and digits <= str(maximum)))
    number = int(("-" if value.startswith("-") else "") + digits)
    check(-maximum <= number <= maximum and (not positive or number > 0))
    return number


def hexadecimal(value):
    check(value is not None and re.fullmatch(r"[0-9a-fA-F]{8}", value))


class Grammar(StyleGrammar):
    def container(self, node):
        check(not (node.text or "").strip(" \t\r\n"))
        check(all(not (n.tail or "").strip(" \t\r\n") for n in node))

    def leaf(self, node):
        check(not len(node) and not (node.text or "").strip(" \t\r\n"))

    def ordered(self, node, names, repeated=()):
        children = self.children(node, set(names), repeated)
        previous = -1
        for child in children:
            index = names.index(self.name(child))
            check(index >= previous)
            previous = index
        return children

    def value(self, node):
        self.leaf(node)
        self.attrs(node, {"val"}, {"val"})
        return self.attr(node, "val")

    def paragraph(self, node):
        self.attrs(node)
        for child in self.ordered(node, ("tabs", "ind")):
            if self.name(child) == "tabs":
                self.attrs(child)
                tabs = self.children(child, {"tab"}, {"tab"})
                check(bool(tabs))
                for tab in tabs:
                    self.leaf(tab)
                    self.attrs(tab, {"val", "pos", "leader"}, {"val", "pos"})
                    check(
                        self.attr(tab, "val")
                        in {"num", "left", "right", "center", "clear", "decimal", "bar"}
                    )
                    check(
                        "purl.oclc.org" not in self.ns
                        or self.attr(tab, "val") not in {"left", "right"}
                    )
                    integer(self.attr(tab, "pos"), signed=True)
                    check(
                        self.attr(tab, "leader")
                        in {None, "none", "dot", "hyphen", "underscore", "heavy", "middleDot"}
                    )
            else:
                self.leaf(child)
                edges = {"start", "end", "hanging", "firstLine"}
                if "purl.oclc.org" not in self.ns:
                    edges |= {"left", "right"}
                self.attrs(child, edges | {n + "Chars" for n in edges})
                for name, value in child.attrib.items():
                    name = name[len(self.ns) :]
                    integer(value, signed=name in {"left", "right", "start", "end"})

    def level(self, node):
        self.attrs(node, {"ilvl", "tplc", "tentative"}, {"ilvl"})
        level = integer(self.attr(node, "ilvl"), maximum=8)
        if self.attr(node, "tplc") is not None:
            hexadecimal(self.attr(node, "tplc"))
        if self.attr(node, "tentative") is not None:
            boolean(self.attr(node, "tentative"))
        for child in self.ordered(
            node,
            ("start", "numFmt", "lvlRestart", "isLgl", "suff", "lvlText", "lvlJc", "pPr", "rPr"),
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
                if name in {"start", "lvlRestart"}:
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

    def abstract(self, node):
        self.attrs(node, {"abstractNumId"}, {"abstractNumId"})
        key, levels = integer(self.attr(node, "abstractNumId")), set()
        for child in self.ordered(node, ("nsid", "multiLevelType", "tmpl", "name", "lvl"), {"lvl"}):
            name = self.name(child)
            if name == "lvl":
                level = self.level(child)
                check(level not in levels)
                levels.add(level)
            else:
                value = self.value(child)
                if name in {"nsid", "tmpl"}:
                    hexadecimal(value)
                elif name == "multiLevelType":
                    check(value in {"singleLevel", "multilevel", "hybridMultilevel"})
        return key, levels

    def number(self, node, definitions):
        self.attrs(node, {"numId"}, {"numId"})
        key = integer(self.attr(node, "numId"), positive=True)
        children = self.ordered(node, ("abstractNumId", "lvlOverride"), {"lvlOverride"})
        check(bool(children) and self.name(children[0]) == "abstractNumId")
        target = integer(self.value(children[0]))
        check(target in definitions)
        seen = set()
        for override in children[1:]:
            self.attrs(override, {"ilvl"}, {"ilvl"})
            level = integer(self.attr(override, "ilvl"), maximum=8)
            check(level not in seen and level in definitions[target])
            seen.add(level)
            for child in self.ordered(override, ("startOverride", "lvl")):
                if self.name(child) == "lvl":
                    check(self.level(child) == level)
                else:
                    integer(self.value(child))
        return key

    def prove(self):
        check(self.name(self.root) == "numbering")
        self.attrs(self.root)
        definitions, instances = {}, set()
        for node in self.ordered(
            self.root, ("abstractNum", "num", "numIdMacAtCleanup"), {"abstractNum", "num"}
        ):
            name = self.name(node)
            if name == "abstractNum":
                key, levels = self.abstract(node)
                check(key not in definitions)
                definitions[key] = levels
            elif name == "num":
                key = self.number(node, definitions)
                check(key not in instances)
                instances.add(key)
            else:
                integer(self.value(node))
