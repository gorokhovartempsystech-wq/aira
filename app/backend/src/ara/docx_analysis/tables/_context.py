"""Recognize actual parent identities before interpreting table properties."""

from ara.docx_package.projection import SourceAnchor

from ._models import TableIssue
from ._parse import word_name

PARENTS = {
    "tblPr": "tbl",
    "tblGrid": "tbl",
    "gridCol": "tblGrid",
    "tr": "tbl",
    "trPr": "tr",
    "tc": "tr",
    "tcPr": "tc",
    "gridSpan": "tcPr",
    "vMerge": "tcPr",
    "gridBefore": "trPr",
    "gridAfter": "trPr",
}
REVISIONS = {
    "hMerge",
    "tblPrChange",
    "tblGridChange",
    "trPrChange",
    "tcPrChange",
    "cellIns",
    "cellDel",
    "cellMerge",
}
RELEVANT = set(PARENTS) | REVISIONS | {"tbl"}


class Blocked(Exception):
    def __init__(self, code, anchor):
        self.issue = TableIssue(code, anchor)
        super().__init__(code)


class Context:
    def __init__(self, root, source):
        self.ns = root.tag.rpartition("}")[0] + "}"
        self.body = self.body_for(root)
        part_name = self.part_name_for(source)
        self.anchors, self.parents, self.tables = {}, {}, []
        recognized = {n: set() for n in RELEVANT}
        stack = [(root, self.root_path_for(root), None)]
        while stack:
            node, path, parent = stack.pop()
            self.anchors[node] = self.anchor_for(node, path, source.sha256, part_name)
            parent = self.parent_for(node, parent, recognized)
            self.parents[node] = parent
            if self.skip_history(node, parent, recognized):
                continue
            name = word_name(node.tag)
            if name in RELEVANT:
                self.require(node.tag == self.ns + name, node, "unsupported_table_context")
                if name in REVISIONS:
                    self.fail("unsupported_table_revision", node)
                if name == "tbl":
                    valid = parent is self.body or parent in recognized["tc"]
                    self.require(valid, node, "unsupported_table_context")
                    self.tables.append(node)
                else:
                    self.require(
                        parent in recognized[PARENTS[name]], node, "unsupported_table_context"
                    )
                recognized[name].add(node)
            elif name in ("ins", "del") and parent in recognized["trPr"]:
                self.fail("unsupported_table_revision", node)
            stack.extend((n, path + (i,), node) for i, n in reversed(list(enumerate(node))))

    def parent_for(self, node, parent, recognized):
        return parent

    def skip_history(self, node, parent, recognized):
        return False

    def part_name_for(self, source):
        return source.main_part

    def anchor_for(self, node, path, sha, part):
        return SourceAnchor(sha, part, path)

    def root_path_for(self, root):
        return ()

    def body_for(self, root):
        return next(n for n in root if n.tag == self.ns + "body")

    def name(self, node):
        return node.tag[len(self.ns) :] if node.tag.startswith(self.ns) else ""

    def fail(self, code, node):
        raise Blocked(code, self.anchors[node])

    def require(self, value, node, code="invalid_table_markup"):
        if not value:
            self.fail(code, node)

    def optional_anchor(self, node):
        return self.anchors[node] if node is not None else None
