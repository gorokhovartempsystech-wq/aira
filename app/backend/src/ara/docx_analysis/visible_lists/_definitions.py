"""Active source facts from the closed unbound grammar; unsupported semantics refuse."""

from dataclasses import dataclass

from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_unlisted._grammar import Grammar, integer
from ara.docx_analysis.visible_unlisted._numbering import RELATIONS, verified
from ara.docx_package.projection import SourceAnchor


def require(value, code="unsupported_active_numbering"):
    if not value:
        raise Refusal(code)


@dataclass(frozen=True)
class Definition:
    level_anchor: SourceAnchor
    instance_anchor: SourceAnchor
    override_anchor: SourceAnchor | None
    start: int
    format: str
    template: str
    suffix: str

    def label(self, ordinal):
        if self.format == "bullet":
            budget(len(self.template), 4096)
            return self.template
        number = str(ordinal)
        size = len(self.template) + self.template.count("%1") * (len(number) - 2)
        budget(size, 4096)
        return self.template.replace("%1", number)


class Definitions:
    def __init__(self, data, source, bounds, namespace):
        self.part, self.linked, self.cache = None, False, {}
        result, self.failed = verified(data, source, bounds, namespace)
        self.abstracts, self.instances = {}, {}
        if result is None:
            return
        self.part, root = result
        self.g = Grammar(root, source.sha256, self.part)
        self.linked = any(
            r.source_part == source.main_part
            and r.relationship_type in RELATIONS
            and r.target_mode == "Internal"
            and r.resolved_part == self.part
            for r in source.relationships
        )
        for node in root:
            name = self.g.name(node)
            if name == "abstractNum":
                self.abstracts[integer(self.g.attr(node, "abstractNumId"))] = node
            elif name == "num":
                self.instances[integer(self.g.attr(node, "numId"))] = node

    def child(self, node, name):
        return next((n for n in node if self.g.name(n) == name), None)

    def value(self, node, name, default=None):
        child = self.child(node, name)
        return default if child is None else self.g.attr(child, "val")

    def resolve(self, num_id):
        require(
            not self.failed and self.linked and num_id in self.instances,
            "unresolved_list_reference",
        )
        if num_id in self.cache:
            return self.cache[num_id]
        instance = self.instances[num_id]
        abstract = self.abstracts[integer(self.value(instance, "abstractNumId"))]
        require(self.value(abstract, "multiLevelType") in (None, "singleLevel"))
        levels = [n for n in abstract if self.g.name(n) == "lvl"]
        require(len(levels) == 1 and integer(self.g.attr(levels[0], "ilvl")) == 0)
        level = levels[0]
        fmt, suffix = self.value(level, "numFmt", "decimal"), self.value(level, "suff", "tab")
        require(fmt in ("decimal", "bullet"))
        require(integer(self.value(level, "lvlRestart", "0")) == 0)
        require(self.value(level, "isLgl", "false") in ("false", "0", "off"))
        text = self.child(level, "lvlText")
        require(text is not None and self.g.attr(text, "null") in (None, "false", "0", "off"))
        template = self.g.attr(text, "val")
        budget(len(template), 8192 if fmt == "decimal" else 4096)
        if fmt == "decimal":
            # %10 is ambiguous outside the fixed single-level subset, not '%1' plus zero.
            tokens = template.split("%1")
            require(all("%" not in value for value in tokens))
            require(all(not value or not value[0].isdigit() for value in tokens[1:]))
        else:
            require("%" not in template)
        properties = self.child(level, "rPr")
        require(
            properties is None
            or not any(self.g.name(n) in {"vanish", "specVanish", "webHidden"} for n in properties)
        )
        start, override_anchor = integer(self.value(level, "start", "0")), None
        for override in instance:
            if self.g.name(override) != "lvlOverride":
                continue
            require(self.child(override, "lvl") is None)
            start_node = self.child(override, "startOverride")
            if start_node is not None:
                start = integer(self.g.attr(start_node, "val"))
                override_anchor = self.g.anchors[start_node]
        result = Definition(
            self.g.anchors[level],
            self.g.anchors[instance],
            override_anchor,
            start,
            fmt,
            template,
            suffix,
        )
        self.cache[num_id] = result
        return result
