"""Private proofs from the same original tree, never caller-provided capabilities."""

from dataclasses import dataclass

from ara.docx_analysis.grid_tables import GridTableLimits, TableCatalogError
from ara.docx_analysis.grid_tables._geometry import GridGeometry
from ara.docx_analysis.moves import _index
from ara.docx_analysis.retained_tables._context import RetainedContext
from ara.docx_analysis.tables._context import Blocked
from ara.docx_analysis.visible_main._models import VisibleViewError

from ._parse import caps


@dataclass(frozen=True)
class TableProof:
    status: str
    tables: tuple
    histories: tuple
    revisions: tuple


@dataclass(frozen=True)
class MoveProof:
    status: str
    pairs: tuple


class StoryTables(RetainedContext):
    def __init__(self, root, source, part, is_main, section_catalog):
        self.original_part = part
        self.is_main = is_main
        self.section_histories = {h.anchor for h in section_catalog.histories} if is_main else set()
        super().__init__(root, source)

    def part_name_for(self, source):
        return self.original_part

    def body_for(self, root):
        return super().body_for(root) if self.is_main else root

    def skip_history(self, node, parent, recognized):
        if self.anchors[node] in self.section_histories:
            return True
        return super().skip_history(node, parent, recognized)


def prove(
    root, source, part, is_main, section_catalog, limits, *, context_type=None, anchor_for=None
):
    try:
        context = (context_type or StoryTables)(root, source, part, is_main, section_catalog)
        geometry = GridGeometry(context, GridTableLimits(**caps(limits)))
        tables = tuple(geometry.table(node) for node in context.tables)
        table = TableProof(
            "indexed" if tables else "absent",
            tables,
            tuple(context.histories),
            tuple(context.revisions),
        )
    except Blocked:
        table = TableProof("blocked", (), (), ())
    except TableCatalogError:
        raise VisibleViewError("view_limit_exceeded") from None
    ns = root.tag.rpartition("}")[0] + "}"
    container = next(n for n in root if n.tag == ns + "body") if is_main else root
    try:
        pairs = _index.index(
            root, source, part_name=part, container=container, anchor_for=anchor_for
        )
        move = MoveProof("indexed" if pairs else "absent", pairs)
    except _index.Blocked:
        move = MoveProof("blocked", ())
    return table, move
