"""Current paragraph pagination only; active numbering remains unproved here."""

from ara.docx_analysis.visible_floating_images._reader import FloatingReader
from ara.docx_analysis.visible_main._reader import boolean, check


class UnlistedReader(FloatingReader):
    def formatting_property(self, node, kind):
        if kind == "pPr" and self.name(node) == "widowControl":
            check(not len(node) and not (node.text or "").strip(" \t\r\n"))
            self.attrs(node, {"val"})
            boolean(self.attr(node, "val"))
            return
        return super().formatting_property(node, kind)
