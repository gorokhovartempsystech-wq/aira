"""Both direct and inherited selections precede paragraph-spanning field checks."""

from ara.docx_analysis.visible_lists._reader import ListReader as DirectReader
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_unlisted._reader import UnlistedReader


class ListReader(DirectReader):
    def __init__(self, *args, **kwargs):
        self.explicit_lists = set()
        super().__init__(*args, **kwargs)

    def formatting_property(self, node, kind):
        if kind == "pPr" and self.name(node) == "numPr":
            # A valid explicit numId0 cancels inheritance even though it creates no item.
            super().formatting_property(node, kind)
            parent = self.logical_parents[node]
            self.explicit_lists.add(self.anchors[self.logical_parents[parent]])
            return
        return super().formatting_property(node, kind)

    def plans(self):
        plans = UnlistedReader.plans(self)
        self.lists.attach(self, plans)
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
                for child in subject.node:
                    if self.name(child) == "fldChar":
                        marker = self.attr(child, "fldCharType")
                        depth += 1 if marker == "begin" else -1 if marker == "end" else 0
        return plans
