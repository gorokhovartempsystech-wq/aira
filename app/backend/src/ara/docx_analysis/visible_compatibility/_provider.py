"""Private composition of one freshly prepared source, never a caller capability."""

from ara.docx_analysis.compatibility_contexts._anchors import original_anchor
from ara.docx_analysis.visible_main._models import VisibleCoverage
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_notes._proofs import part_move_identities, prove_note
from ara.docx_analysis.visible_stories._proofs import prove

from ._reader import SourceNoteTables, SourceStoryTables

DECISIONS = {
    "ignore_element": ("excluded", "compatibility_ignored_element"),
    "unwrap_element": ("metadata", "compatibility_unwrapped_element"),
    "strip_attributes": ("metadata", "compatibility_attributes"),
    "alternate_content": ("metadata", "compatibility_alternate_selection"),
}


class Provider:
    def __init__(self, prepared):
        self.prepared = prepared
        self.roots = {part.part_name: part.root for part in prepared.view.parts}

    def metadata(self):
        c = self.prepared.contexts
        return c.styles, self.style_proof, c.sections, c.notes

    def style_proof(self, context):
        if context is not self.prepared.contexts.styles:
            raise Refusal("style_context_blocked")
        return self.prepared.contexts.table_styles

    def tree(self, data, part, bounds):
        return self.roots[part]

    def anchors(self, source, part):
        return lambda node, path: original_anchor(node, path, source.sha256, part)

    def prove(self, root, source, part, kind, path, sections, limits):
        anchors = self.anchors(source, part)
        if kind in ("footnote", "endnote"):
            return prove_note(
                root,
                source,
                part,
                path,
                sections,
                limits,
                context_type=SourceNoteTables,
                anchor_for=anchors,
            )
        return prove(
            root,
            source,
            part,
            kind == "main",
            sections,
            limits,
            context_type=SourceStoryTables,
            anchor_for=anchors,
        )

    def check_note_part(self, root, source, part):
        part_move_identities(root, source, part, anchor_for=self.anchors(source, part))

    def note_node(self, tree, target):
        node = self.prepared.view.node(target)
        if node is None or tree.anchor.part_name != target.part_name:
            raise Refusal("unresolved_note_reference")
        return node

    def coverage(self):
        for part in self.prepared.view.catalog.parts:
            for action in part.actions:
                status, code = DECISIONS[action.kind]
                yield VisibleCoverage(status, code, part.part_name, action.anchor, None)
