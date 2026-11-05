"""The one additional ordinary paragraph property affects spacing, not text."""

from ara.docx_analysis.visible_main._reader import boolean, check
from ara.docx_analysis.visible_style_lists._reader import ListReader


class Reader(ListReader):
    def formatting_property(self, node, kind):
        if kind == "pPr" and self.name(node) == "contextualSpacing":
            check(not len(node) and not (node.text or "").strip(" \t\r\n"))
            self.attrs(node, {"val"})
            boolean(self.attr(node, "val"))
            return
        return super().formatting_property(node, kind)
