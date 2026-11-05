"""Exclude previous properties only after proving their real current owner."""

import re

from ara.docx_analysis.tables._context import Context
from ara.docx_analysis.tables._parse import word_name

from ._models import TablePropertyHistory

HISTORIES = {
    "tblPrChange": ("tblPr", "table"),
    "tblGridChange": ("tblGrid", "grid"),
    "trPrChange": ("trPr", "row"),
    "tcPrChange": ("tcPr", "cell"),
}


class CurrentContext(Context):
    def __init__(self, root, source):
        self.histories, self.history_nodes, self.history_owners = [], set(), set()
        super().__init__(root, source)

    def skip_history(self, node, parent, recognized):
        name = word_name(node.tag)
        if name not in HISTORIES:
            return False
        owner, kind = HISTORIES[name]
        self.require(
            node.tag == self.ns + name and parent in recognized[owner],
            node,
            "unsupported_table_context",
        )
        code = "invalid_table_history"
        self.require(parent not in self.history_owners and parent[-1] is node, node, code)
        allowed = {"id"} if kind == "grid" else {"id", "author", "date"}
        identity = node.get(self.ns + "id")
        self.require(
            set(node.attrib) <= {self.ns + n for n in allowed}
            and identity is not None
            and re.fullmatch(r"[+-]?[0-9]{1,20}", identity) is not None,
            node,
            code,
        )
        self.require(
            not (node.text or "").strip() and not (node.tail or "").strip() and len(node) == 1,
            node,
            code,
        )
        previous = node[0]
        self.require(
            previous.tag == self.ns + owner
            and not previous.attrib
            and not (previous.text or "").strip()
            and not (previous.tail or "").strip()
            and all(not (child.tail or "").strip() for child in previous),
            node,
            code,
        )
        anchor = self.anchors[node]
        self.histories.append(
            TablePropertyHistory(
                kind,
                anchor,
                self.anchors[parent],
                self.anchor_for(
                    previous, anchor.path + (0,), anchor.source_sha256, anchor.part_name
                ),
            )
        )
        self.history_nodes.add(node)
        self.history_owners.add(parent)
        return True
