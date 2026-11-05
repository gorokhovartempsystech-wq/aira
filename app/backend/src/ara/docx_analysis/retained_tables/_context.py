"""Prove each excluded cell before skipping any of its semantic descendants."""

import re

from ara.docx_analysis.current_tables._context import CurrentContext
from ara.docx_analysis.tables._context import Blocked
from ara.docx_analysis.tables._parse import word_name

from ._models import TableRevision

CELL_REVISIONS = {"cellIns", "cellDel", "cellMerge", "hMerge"}


def require(value, anchor, code="invalid_table_revision"):
    if not value:
        raise Blocked(code, anchor)


def container(node):
    return not (node.text or "").strip() and all(not (n.tail or "").strip() for n in node)


class RetainedContext(CurrentContext):
    def __init__(self, root, source):
        self.revisions, self.deleted_cells = [], set()
        super().__init__(root, source)

    def revision(self, node, anchor):
        identity = node.get(self.ns + "id")
        require(
            not len(node)
            and not (node.text or "").strip()
            and not (node.tail or "").strip()
            and set(node.attrib) <= {self.ns + n for n in ("id", "author", "date")}
            and identity is not None
            and re.fullmatch(r"[+-]?[0-9]{1,20}", identity) is not None,
            anchor,
        )

    def deleted(self, node, parent, recognized):
        properties = [(i, n) for i, n in enumerate(node) if word_name(n.tag) == "tcPr"]
        markers = [
            (i, prop, j, child)
            for i, prop in properties
            for j, child in enumerate(prop)
            if word_name(child.tag) == "cellDel"
        ]
        if not markers:
            return False
        subject = self.anchors[node]
        require(
            node.tag == self.ns + "tc" and parent in recognized["tr"],
            subject,
            "unsupported_table_context",
        )
        require(len(properties) == 1 and properties[0][0] == 0, subject)
        index, properties_node, child_index, marker = markers[0]
        owner = self.anchor_for(
            properties_node, subject.path + (index,), subject.source_sha256, subject.part_name
        )
        anchor = self.anchor_for(
            marker, owner.path + (child_index,), owner.source_sha256, owner.part_name
        )
        require(
            properties_node.tag == self.ns + "tcPr" and marker.tag == self.ns + "cellDel",
            anchor,
            "unsupported_table_context",
        )
        require(
            not node.attrib
            and container(node)
            and not properties_node.attrib
            and container(properties_node)
            and len(node) > 1
            and all(n.tag in (self.ns + "p", self.ns + "tbl") for n in list(node)[1:]),
            subject,
        )
        conflicts = [n for n in properties_node if word_name(n.tag) in CELL_REVISIONS]
        require(len(markers) == len(conflicts) == 1, anchor)
        self.revision(marker, anchor)
        self.revisions.append(TableRevision("deleted_cell", anchor, owner, subject))
        self.deleted_cells.add(node)
        return True

    def insertion(self, node, parent, kind, conflicts):
        anchor = self.anchors[node]
        require(sum(word_name(n.tag) in conflicts for n in parent) == 1, anchor)
        self.revision(node, anchor)
        self.revisions.append(
            TableRevision(kind, anchor, self.anchors[parent], self.anchors[self.parents[parent]])
        )

    def skip_history(self, node, parent, recognized):
        if super().skip_history(node, parent, recognized):
            return True
        name = word_name(node.tag)
        if name == "tc" and self.deleted(node, parent, recognized):
            return True
        if name == "ins" and parent in recognized["trPr"]:
            self.require(node.tag == self.ns + name, node, "unsupported_table_context")
            self.insertion(node, parent, "inserted_row", {"ins", "del"})
            return True
        if name == "cellIns":
            self.require(
                node.tag == self.ns + name and parent in recognized["tcPr"],
                node,
                "unsupported_table_context",
            )
            self.insertion(node, parent, "inserted_cell", CELL_REVISIONS)
            return True
        if name == "cellDel":
            self.fail("unsupported_table_context", node)
        return False
