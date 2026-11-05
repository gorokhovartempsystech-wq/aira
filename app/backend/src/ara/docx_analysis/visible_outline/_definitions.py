"""Resolve complete level replacements and Word's abstract-level restart policy."""

from dataclasses import dataclass

from ara.docx_analysis.visible_lists._definitions import Definitions as BaseDefinitions
from ara.docx_analysis.visible_lists._definitions import require
from ara.docx_analysis.visible_unlisted._grammar import integer
from ara.docx_package.projection import SourceAnchor

from ._labels import NUMERIC, template


@dataclass(frozen=True)
class Definition:
    level: int
    level_anchor: SourceAnchor
    instance_anchor: SourceAnchor
    override_anchor: SourceAnchor | None
    start: int
    format: str
    pieces: tuple[str | int, ...]
    suffix: str
    restart: int
    legal: bool


class Definitions(BaseDefinitions):
    def resolve(self, num_id, index):
        require(
            not self.failed and self.linked and num_id in self.instances,
            "unresolved_list_reference",
        )
        key = (num_id, index)
        if key in self.cache:
            return self.cache[key]
        instance = self.instances[num_id]
        abstract = self.abstracts[integer(self.value(instance, "abstractNumId"))]
        base = next(
            (
                n
                for n in abstract
                if self.g.name(n) == "lvl" and integer(self.g.attr(n, "ilvl")) == index
            ),
            None,
        )
        require(base is not None, "unresolved_list_reference")
        restart = integer(self.value(base, "lvlRestart", str(index)))
        require(restart <= min(index, 7) or (index == 8 and self.child(base, "lvlRestart") is None))
        override = next(
            (
                n
                for n in instance
                if self.g.name(n) == "lvlOverride" and integer(self.g.attr(n, "ilvl")) == index
            ),
            None,
        )
        replacement = None if override is None else self.child(override, "lvl")
        level = base if replacement is None else replacement
        fmt, suffix = self.value(level, "numFmt", "decimal"), self.value(level, "suff", "tab")
        require(fmt in (*NUMERIC, "bullet"))
        text = self.child(level, "lvlText")
        require(text is not None and self.g.attr(text, "null") in (None, "false", "0", "off"))
        pieces = template(self.g.attr(text, "val"), fmt, index)
        properties = self.child(level, "rPr")
        require(
            properties is None
            or not any(self.g.name(n) in {"vanish", "specVanish", "webHidden"} for n in properties)
        )
        start_node = None if override is None else self.child(override, "startOverride")
        start = integer(
            self.value(level, "start", "0")
            if start_node is None
            else self.g.attr(start_node, "val")
        )
        result = Definition(
            index,
            self.g.anchors[level],
            self.g.anchors[instance],
            None if start_node is None else self.g.anchors[start_node],
            start,
            fmt,
            pieces,
            suffix,
            restart,
            self.value(level, "isLgl", "false") not in ("false", "0", "off"),
        )
        self.cache[key] = result
        return result
