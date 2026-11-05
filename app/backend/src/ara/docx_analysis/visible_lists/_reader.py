"""Direct properties and paragraph field boundaries are proved before assembly."""

from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_unlisted._reader import UnlistedReader


class ListReader(UnlistedReader):
    def __init__(self, *args, lists, **kwargs):
        self.lists, self.direct_lists = lists, {}
        super().__init__(*args, **kwargs)

    def formatting_property(self, node, kind):
        if kind == "pPr" and self.name(node) == "numPr":
            self.lists.select(self, node)
            return
        return super().formatting_property(node, kind)

    def plans(self):
        plans = super().plans()
        depth = 0
        for kind, paragraph, subject in self.field_tokens:
            if kind in ("paragraph_start", "paragraph_end"):
                if depth and self.anchors[paragraph] in self.direct_lists:
                    raise Refusal("unsupported_list_field_boundary")
            elif kind == "simple_enter":
                depth += 1
            elif kind == "simple_exit":
                depth -= 1
            elif kind == "run":
                # Ordinary field State already validated these original children. Its
                # filtered atoms no longer contain the boundary markers we need here.
                for child in subject.node:
                    if self.name(child) == "fldChar":
                        marker = self.attr(child, "fldCharType")
                        depth += 1 if marker == "begin" else -1 if marker == "end" else 0
        return plans
