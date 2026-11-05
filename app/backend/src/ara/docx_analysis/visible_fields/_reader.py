"""Closed field grammar on original plans; no field commands are interpreted."""

from ara.docx_analysis.visible_main._reader import XML_SPACE, Refusal, boolean, check
from ara.docx_analysis.visible_notes._reader import NoteReader

from ._state import State


class FieldReader(NoteReader):
    def __init__(self, *args, **kwargs):
        self.field_tokens, self.section_boundaries = [], set()
        self.current_paragraph = None
        super().__init__(*args, **kwargs)

    def flags(self, node):
        for key in ("fldLock", "dirty"):
            value = self.attr(node, key)
            if value is not None:
                flag = boolean(value)
                if key == "dirty" and flag:
                    raise Refusal("invalidated_field_result")

    def extended_run(self, child, plan):
        name = self.name(child)
        if name == "fldChar":
            self.leaf(child)
            self.attrs(child, {"fldCharType", "fldLock", "dirty"}, {"fldCharType"})
            kind = self.attr(child, "fldCharType")
            check(kind in ("begin", "separate", "end"))
            self.flags(child)
            plan.atoms.append(("field_" + kind, child, ""))
        elif name == "instrText":
            self.leaf(child, text=True)
            check(set(child.attrib) <= {XML_SPACE})
            check(child.get(XML_SPACE) in (None, "preserve", "default"))
            plan.atoms.append(("field_instruction", child, child.text or ""))
        else:
            super().extended_run(child, plan)

    def extended_inline(self, child, paragraph, *, in_link, top):
        if self.name(child) != "fldSimple":
            return super().extended_inline(child, paragraph, in_link=in_link, top=top)
        self.attrs(child, {"instr", "fldLock", "dirty"}, {"instr"})
        self.container(child)
        self.flags(child)
        self.field_tokens.append(("simple_enter", paragraph.node, child))
        self.inline(child, paragraph, in_link=in_link)
        self.field_tokens.append(("simple_exit", paragraph.node, child))

    def inline(self, node, paragraph, *, in_link=False, top=False):
        previous = self.current_paragraph
        self.current_paragraph = paragraph
        if top:
            self.field_tokens.append(("paragraph_start", paragraph.node, None))
        try:
            super().inline(node, paragraph, in_link=in_link, top=top)
            if top:
                self.field_tokens.append(("paragraph_end", paragraph.node, None))
        finally:
            self.current_paragraph = previous

    def run(self, node):
        result = super().run(node)
        self.field_tokens.append(("run", self.current_paragraph.node, result))
        return result

    def section_properties(self, node):
        super().section_properties(node)
        if self.current_paragraph is not None:
            self.section_boundaries.add(self.current_paragraph.node)

    def table_plans(self, table):
        self.field_tokens.append(("barrier", None, table.anchor))
        plans = super().table_plans(table)
        self.field_tokens.append(("barrier", None, table.anchor))
        return plans

    def plans(self):
        plans = super().plans()
        State(self).consume(self.field_tokens)
        return plans
