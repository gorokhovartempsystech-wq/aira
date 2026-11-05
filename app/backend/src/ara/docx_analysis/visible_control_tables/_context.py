"""Original parents and proven control-mediated table parents remain distinct."""

from ara.docx_analysis.tables._parse import word_name
from ara.docx_analysis.visible_stories._proofs import StoryTables

ROLES = {"block": {"p", "tbl"}, "row": {"tr"}, "cell": {"tc"}}


class ControlContext(StoryTables):
    def __init__(self, reader, sections):
        self.reader = reader
        self.original_parents, self.controls, self.contents = {}, {}, {}
        self.expansions = {}
        super().__init__(
            reader.root, reader.source, reader.part_name, reader.kind == "main", sections
        )
        for node in self.controls:
            self.control_children(node)

    def root_path_for(self, root):
        return self.reader.original_path

    def parent_for(self, node, parent, recognized):
        self.original_parents[node] = parent
        return self.contents.get(parent, parent)

    def skip_history(self, node, parent, recognized):
        if super().skip_history(node, parent, recognized):
            return True
        if word_name(node.tag) != "sdt":
            return False
        role = (
            "block"
            if parent is self.body or parent in recognized["tc"]
            else "row"
            if parent in recognized["tbl"]
            else "cell"
            if parent in recognized["tr"]
            else None
        )
        if role is not None:
            self.require(node.tag == self.ns + "sdt", node, "unsupported_control_context")
            content = self.reader.control_content(node)
            self.controls[node] = (role, parent, content)
            if content is not None:
                self.contents[content] = parent
        return False

    def control_children(self, node):
        if node in self.expansions:
            return self.expansions[node]
        role, owner, content = self.controls[node]
        result = []
        if content is not None:
            for child in content:
                if child in self.controls:
                    child_role, child_owner, _ = self.controls[child]
                    self.require(
                        child_role == role and child_owner is owner,
                        child,
                        "unsupported_control_context",
                    )
                    result.extend(self.control_children(child))
                else:
                    self.require(
                        self.name(child) in ROLES[role] and self.parents[child] is owner,
                        child,
                        "unsupported_control_context",
                    )
                    result.append(child)
        if role != "block":
            self.require(len(result) <= 1, node, "unsupported_control_cardinality")
        self.expansions[node] = tuple(result)
        return self.expansions[node]

    def expanded(self, node):
        for child in node:
            if child in self.controls:
                self.require(self.controls[child][1] is node, child, "unsupported_control_context")
                yield from self.control_children(child)
            else:
                yield child
