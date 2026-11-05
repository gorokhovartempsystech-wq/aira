"""Traverse actual control children without changing their XML paths or ownership."""

from ara.docx_analysis.visible_fields._reader import FieldReader
from ara.docx_analysis.visible_main._reader import Refusal

from ._grammar import Grammar


class ControlReader(FieldReader):
    def grammar_type(self):
        return Grammar

    def control_content(self, node):
        return self.grammar_type()(self).content(node)

    def barrier(self, node):
        self.field_tokens.append(("barrier", None, self.anchors[node]))

    def extended_inline(self, child, paragraph, *, in_link, top):
        if self.name(child) != "sdt":
            return super().extended_inline(child, paragraph, in_link=in_link, top=top)
        content = self.control_content(child)
        self.barrier(child)
        if content is not None:
            self.inline(content, paragraph, in_link=in_link)
        self.barrier(child)

    def block_plans(self, node):
        if self.name(node) != "sdt":
            return super().block_plans(node)
        content = self.control_content(node)
        self.barrier(node)
        result = []
        if content is not None:
            result.extend(self.control_block_plans(content))
        self.barrier(node)
        return result

    def control_block_plans(self, content):
        result = []
        for child in content:
            if self.name(child) not in ("p", "sdt"):
                raise Refusal("unsupported_control_block")
            result.extend(self.block_plans(child))
        return result
