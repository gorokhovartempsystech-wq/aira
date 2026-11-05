"""Original note subtrees keep physical prefixes; range identities remain part-wide."""

from ara.docx_analysis.grid_tables import GridTableLimits, TableCatalogError
from ara.docx_analysis.grid_tables._geometry import GridGeometry
from ara.docx_analysis.moves import _index
from ara.docx_analysis.moves._parse import move_name
from ara.docx_analysis.tables._context import Blocked
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_main._reader import Refusal
from ara.docx_analysis.visible_stories._parse import caps
from ara.docx_analysis.visible_stories._proofs import MoveProof, StoryTables, TableProof
from ara.docx_package.projection import SourceAnchor


class NoteTables(StoryTables):
    def __init__(self, root, source, part, path, sections):
        self.original_path = path
        super().__init__(root, source, part, False, sections)

    def root_path_for(self, root):
        return self.original_path


def part_move_identities(root, source, part, *, anchor_for=None):
    ns = root.tag.rpartition("}")[0] + "}"
    identities, names = set(), set()
    stack = [(root, ())]
    make_anchor = anchor_for or (lambda node, path: SourceAnchor(source.sha256, part, path))
    try:
        while stack:
            node, path = stack.pop()
            name = move_name(node.tag)
            if name in ("moveFromRangeStart", "moveToRangeStart"):
                anchor = make_anchor(node, path)
                _index.require(node.tag == ns + name, anchor)
                identity, group = _index.attributes(node, name, ns, anchor)
                kind = "from" if name.startswith("moveFrom") else "to"
                _index.require(
                    (kind, identity) not in identities and (kind, group) not in names,
                    anchor,
                    "duplicate_range_id",
                )
                identities.add((kind, identity))
                names.add((kind, group))
            stack.extend((n, path + (i,)) for i, n in enumerate(node))
    except _index.Blocked:
        raise Refusal("move_catalog_blocked") from None


def prove_note(root, source, part, path, sections, limits, *, context_type=None, anchor_for=None):
    try:
        context = (context_type or NoteTables)(root, source, part, path, sections)
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
    try:
        pairs = _index.index(
            root, source, part_name=part, container=root, root_path=path, anchor_for=anchor_for
        )
        move = MoveProof("indexed" if pairs else "absent", pairs)
    except _index.Blocked:
        move = MoveProof("blocked", ())
    return table, move
