"""Validate retained row widths against the explicit current source grid."""

from ara.docx_analysis.current_tables._geometry import CurrentGeometry


class RetainedGeometry(CurrentGeometry):
    def children(self, node, prop, allowed, *, row=False):
        properties, children = super().children(node, prop, allowed, row=row)
        if row:
            children = [n for n in children if n not in self.c.deleted_cells]
        return properties, children
