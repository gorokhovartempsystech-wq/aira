"""Keep outline semantics while proving the actual applied-style level association."""

from ara.docx_analysis.visible_outline._definitions import Definitions as OutlineDefinitions
from ara.docx_analysis.visible_outline._definitions import require
from ara.docx_analysis.visible_unlisted._grammar import integer

from ._grammar import Grammar
from ._numbering import RELATIONS, verified


class Definitions(OutlineDefinitions):
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

    def bound_level(self, num_id, style_id):
        require(
            not self.failed and self.linked and num_id in self.instances,
            "unresolved_list_reference",
        )
        instance = self.instances[num_id]
        abstract = self.abstracts[integer(self.value(instance, "abstractNumId"))]
        matches = [
            n for n in abstract if self.g.name(n) == "lvl" and self.value(n, "pStyle") == style_id
        ]
        require(len(matches) == 1, "unresolved_style_list_binding")
        level = matches[0]
        binding = self.child(level, "pStyle")
        return self.resolve(num_id, integer(self.g.attr(level, "ilvl"))), self.g.anchors[binding]
