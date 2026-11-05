"""Private zero-text marker atoms pass through the same effective run visibility."""

import re

from ara.docx_analysis.visible_main._reader import Refusal, boolean, check
from ara.docx_analysis.visible_stories._reader import StoryReader

REFERENCE = "note_reference"
LABEL = "note_label"


class NoteReader(StoryReader):
    def __init__(self, *args, path=(), **kwargs):
        self.original_path = path
        super().__init__(*args, **kwargs)

    def root_path_for(self, root):
        return self.original_path

    def root_properties(self):
        if self.kind in ("footnote", "endnote"):
            check(self.ns == self.main_namespace and self.name(self.root) == self.kind)
            self.attrs(self.root, {"id", "type"}, {"id"})
            self.container(self.root)
        else:
            super().root_properties()

    def extended_run(self, child, plan):
        name = self.name(child)
        if name in ("footnoteReference", "endnoteReference"):
            if self.kind != "main":
                raise Refusal("unsupported_note_reference_context")
            self.leaf(child)
            self.attrs(child, {"id", "customMarkFollows"}, {"id"})
            check(re.fullmatch(r"[+-]?[0-9]{1,20}", self.attr(child, "id")) is not None)
            if self.attr(child, "customMarkFollows") is not None:
                boolean(self.attr(child, "customMarkFollows"))
            plan.atoms.append((REFERENCE, child, ""))
        elif name in ("footnoteRef", "endnoteRef"):
            if name != self.kind + "Ref":
                raise Refusal("unsupported_note_reference_context")
            self.leaf(child)
            self.attrs(child)
            plan.atoms.append((LABEL, child, ""))
        else:
            super().extended_run(child, plan)
