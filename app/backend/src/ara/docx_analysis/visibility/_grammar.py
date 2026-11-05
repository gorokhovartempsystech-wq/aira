"""Read current properties contextually; history and opaque styles stay opaque."""

import re
from dataclasses import dataclass, field

from ara.docx_package.projection import SourceAnchor

from ._models import VisibilityProperties, VisibilityValue, absent

VISIBILITY = ("vanish", "specVanish", "webHidden")
FORMATTING = {
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
}
PARAGRAPH = {"spacing", "ind", "jc", "outlineLvl", "keepNext", "keepLines", "pageBreakBefore"}
UI_BOOL = {
    "autoRedefine",
    "hidden",
    "semiHidden",
    "unhideWhenUsed",
    "qFormat",
    "locked",
    "personal",
    "personalCompose",
    "personalReply",
}


class Unsupported(Exception):
    pass


def check(condition):
    if not condition:
        raise Unsupported()


def boolean(value, default=True):
    if value is None:
        return default
    check(value in ("true", "1", "on", "false", "0", "off"))
    return value in ("true", "1", "on")


def identity(value):
    check(value is not None and 1 <= len(value) <= 253)
    return value


def decimal(value):
    check(value is not None and re.fullmatch(r"[0-9]+", value) is not None)
    normalized = value.lstrip("0") or "0"
    check(len(normalized) < 10 or (len(normalized) == 10 and normalized <= "2147483647"))


@dataclass
class Definition:
    identity: str = field(repr=False)
    kind: str
    anchor: SourceAnchor = field(repr=False)
    default: bool
    parent: str | None = field(default=None, repr=False)
    properties: VisibilityProperties = field(default_factory=absent)
    code: str | None = None


class Grammar:
    def __init__(self, root, sha, part):
        self.root = root
        self.ns = root.tag.rpartition("}")[0] + "}"
        self.anchors = {}
        stack = [(root, ())]
        while stack:
            node, path = stack.pop()
            self.anchors[node] = self.anchor_for(node, path, sha, part)
            stack.extend((n, path + (i,)) for i, n in enumerate(node))

    def anchor_for(self, node, path, sha, part):
        return SourceAnchor(sha, part, path)

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

    def leaf(self, node):
        check(not len(node) and not (node.text or "").strip())

    def children(self, node, allowed, repeated=()):
        self.container(node)
        seen = set()
        for child in node:
            name = self.name(child)
            check(name in allowed and (name in repeated or name not in seen))
            seen.add(name)
        return list(node)

    def envelope(self):
        self.attrs(self.root)
        return self.children(self.root, {"docDefaults", "latentStyles", "style"}, {"style"})

    def identities(self, children):
        definitions = {}
        defaults = {}
        duplicate_default = False
        for node in children:
            if self.name(node) != "style":
                continue
            self.attrs(node, {"styleId", "type", "default", "customStyle"}, {"styleId", "type"})
            key = identity(self.attr(node, "styleId"))
            kind = self.attr(node, "type")
            check(
                kind in ("paragraph", "character", "table", "numbering") and key not in definitions
            )
            default = boolean(self.attr(node, "default"), False)
            boolean(self.attr(node, "customStyle"), False)
            definitions[key] = (Definition(key, kind, self.anchors[node], default), node)
            if default:
                duplicate_default |= kind in defaults
                defaults[kind] = key
        return definitions, defaults, duplicate_default

    def history(self, node, kind):
        self.attrs(node, {"id", "author", "date"}, {"id"})
        check(re.fullmatch(r"[+-]?[0-9]{1,20}", self.attr(node, "id")) is not None)
        self.container(node)
        check(len(node) == 1 and self.name(node[0]) == kind)
        # Previous properties are not interpreted; their budgets were already checked.

    def property_names(self, kind):
        return (FORMATTING | set(VISIBILITY)) if kind == "rPr" else PARAGRAPH

    def properties(self, node, kind):
        self.attrs(node)
        allowed = self.property_names(kind)
        children = self.children(node, allowed | {kind + "Change"})
        values = dict.fromkeys(VISIBILITY)
        for child in children:
            name = self.name(child)
            if name == kind + "Change":
                self.history(child, kind)
                continue
            self.leaf(child)
            if name in VISIBILITY:
                self.attrs(child, {"val"})
                values[name] = VisibilityValue(
                    boolean(self.attr(child, "val")), self.anchors[child]
                )
            else:
                check(all(a.startswith(self.ns) for a in child.attrib))
        return VisibilityProperties(*(values[n] or VisibilityValue(None, None) for n in VISIBILITY))

    def defaults(self, node):
        self.attrs(node)
        result = absent()
        for child in self.children(node, {"rPrDefault", "pPrDefault"}):
            self.attrs(child)
            kind = "rPr" if self.name(child) == "rPrDefault" else "pPr"
            for prop in self.children(child, {kind}):
                value = self.properties(prop, kind)
                if kind == "rPr":
                    result = value
        return result

    def latent(self, node):
        bools = {"defLockedState", "defSemiHidden", "defUnhideWhenUsed", "defQFormat"}
        nums = {"defUIPriority", "count"}
        self.attrs(node, bools | nums)
        for name in bools:
            if self.attr(node, name) is not None:
                boolean(self.attr(node, name))
        for name in nums:
            if self.attr(node, name) is not None:
                decimal(self.attr(node, name))
        for child in self.children(node, {"lsdException"}, {"lsdException"}):
            self.leaf(child)
            self.attrs(
                child,
                {"name", "locked", "semiHidden", "unhideWhenUsed", "qFormat", "uiPriority"},
                {"name"},
            )
            for name in ("locked", "semiHidden", "unhideWhenUsed", "qFormat"):
                if self.attr(child, name) is not None:
                    boolean(self.attr(child, name))
            if self.attr(child, "uiPriority") is not None:
                decimal(self.attr(child, "uiPriority"))

    def definition(self, d, node):
        if d.kind in ("table", "numbering"):
            d.code = "opaque_style_type"
            return
        try:
            allowed = {
                "basedOn",
                "rPr",
                "name",
                "aliases",
                "next",
                "link",
                "uiPriority",
                "rsid",
            } | UI_BOOL
            if d.kind == "paragraph":
                allowed.add("pPr")
            for child in self.children(node, allowed):
                name = self.name(child)
                if name in ("rPr", "pPr"):
                    value = self.properties(child, name)
                    if name == "rPr":
                        d.properties = value
                    continue
                self.leaf(child)
                self.attrs(child, {"val"}, () if name in UI_BOOL else {"val"})
                value = self.attr(child, "val")
                if name == "basedOn":
                    d.parent = identity(value)
                elif name in UI_BOOL:
                    boolean(value)
                elif name == "uiPriority":
                    decimal(value)
                elif name == "rsid":
                    check(re.fullmatch(r"[0-9a-fA-F]{8}", value) is not None)
        except Unsupported:
            d.code = "unsupported_style_structure"
