"""Use actual proven table children; empty controls cannot repair property order."""

from ara.docx_analysis.grid_tables._geometry import GridGeometry


class ControlGeometry(GridGeometry):
    def child_nodes(self, node):
        kind = self.c.name(node)
        prop = {"tbl": "tblPr", "tr": "trPr", "tc": "tcPr"}[kind]
        grid_position = 1 if len(node) and self.c.name(node[0]) == prop else 0
        for i, child in enumerate(node):
            name = self.c.name(child)
            if name == prop:
                self.c.require(i == 0, child)
            elif kind == "tbl" and name == "tblGrid":
                self.c.require(i == grid_position, child)
        return self.c.expanded(node)
