"""Current columns retain their original addresses around historical grid payload."""

from ara.docx_analysis.tables._geometry import Geometry
from ara.docx_analysis.tables._models import budget


class CurrentGeometry(Geometry):
    def grid_columns(self, grid):
        self.attrs(grid)
        self.container(grid)
        columns = tuple(n for n in grid if n not in self.c.history_nodes)
        self.c.require(bool(columns), grid, "unresolved_table_grid")
        budget(len(columns), self.limits.max_grid_columns)
        for column in columns:
            self.c.require(self.c.name(column) == "gridCol", column, "unsupported_table_context")
            self.leaf(column, {"w"})
        return columns
