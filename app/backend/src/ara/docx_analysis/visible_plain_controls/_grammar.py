"""Declared plain types do not override formatting of their stored children."""

from ara.docx_analysis.visible_controls._grammar import Grammar as RichGrammar
from ara.docx_analysis.visible_main._reader import Refusal, boolean


class Grammar(RichGrammar):
    def __init__(self, reader):
        super().__init__(reader)
        self.plain = False

    def properties(self, node):
        types = [n for n in node if self.r.name(n) in ("text", "richText")]
        if len(types) > 1:
            raise Refusal("unsupported_control_properties")
        super().properties(node)

    def extended_property(self, node):
        if self.r.name(node) != "text":
            return super().extended_property(node)
        self.r.attrs(node, {"multiLine"})
        self.r.leaf(node)
        value = self.r.attr(node, "multiLine")
        if value is not None:
            boolean(value)
        self.plain = True

    def control_code(self):
        return "plain_text_control" if self.plain else super().control_code()

    def content(self, node):
        content = super().content(node)
        if self.plain:
            self.r.plain_controls[node] = content
        return content
