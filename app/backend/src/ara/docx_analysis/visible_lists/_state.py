"""Source selections are separate from sequence consumption and generated text budgets."""

from dataclasses import dataclass

from ara.docx_analysis.visibility._grammar import Unsupported
from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_main._reader import Refusal, check
from ara.docx_analysis.visible_unlisted._grammar import integer

from ._definitions import Definitions, require
from ._models import ListItem


@dataclass(frozen=True)
class Selection:
    num_id: int
    properties: object
    definition: object


class State(Definitions):
    def __init__(self, data, source, bounds, namespace, limits):
        super().__init__(data, source, bounds, namespace)
        self.limits, self.counters, self.items = limits, {}, []
        self.generated, self.used = 0, False

    def select(self, reader, node):
        reader.attrs(node)
        check(not (node.text or "").strip(" \t\r\n"))
        check(all(not (n.tail or "").strip(" \t\r\n") for n in node))
        names = [reader.name(n) for n in node]
        check(names in (["numId"], ["ilvl", "numId"]))
        values = {}
        try:
            for child in node:
                check(not len(child) and not (child.text or "").strip(" \t\r\n"))
                reader.attrs(child, {"val"}, {"val"})
                name = reader.name(child)
                values[name] = integer(
                    reader.attr(child, "val"), maximum=8 if name == "ilvl" else 2147483647
                )
        except Unsupported:
            raise Refusal("unsupported_list_properties") from None
        parent = reader.logical_parents.get(node)
        paragraph = reader.logical_parents.get(parent)
        check(parent is not None and reader.name(parent) == "pPr")
        check(paragraph is not None and reader.name(paragraph) == "p")
        if values["numId"] == 0:
            reader.event("metadata", "numbering_removed", node)
            return
        require(values.get("ilvl") == 0, "unsupported_list_level")
        require(reader.kind == "main", "unsupported_list_story")
        definition = self.resolve(values["numId"])
        self.used = True
        reader.direct_lists[reader.anchors[paragraph]] = Selection(
            values["numId"], reader.anchors[node], definition
        )

    def append(self, paragraph, selection, fragment_ids):
        d, num_id = selection.definition, selection.num_id
        ordinal = self.counters.get(num_id, d.start - 1) + 1
        require(ordinal <= 2147483647, "list_counter_overflow")
        label = d.label(ordinal)
        budget(len(self.items) + 1, self.limits.max_paragraphs)
        self.generated += len(label) + (d.suffix != "nothing")
        budget(self.generated, self.limits.max_text_characters)
        self.counters[num_id] = ordinal
        self.items.append(
            ListItem(
                paragraph,
                selection.properties,
                d.level_anchor,
                d.instance_anchor,
                d.override_anchor,
                num_id,
                0,
                ordinal,
                d.format,
                label,
                d.suffix,
                fragment_ids,
            )
        )
