"""Retained logical cell flows with exact physical source addresses."""

from functools import partial

from ara.docx_analysis import moves, retained_tables
from ara.docx_analysis.visible_current_tables._reader import CurrentProperties, CurrentReader
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_styled_tables._reader import prepare_styles


def prepare_reader(data, source, limits):
    proof_factory = prepare_styles(data, source, limits)
    caps = dict(
        max_xml_nodes=limits.max_xml_nodes,
        max_xml_depth=limits.max_xml_depth,
        max_xml_characters=limits.max_xml_characters,
    )
    try:
        table_catalog = retained_tables.read_retained_table_catalog(
            data, source_sha256=source.sha256, limits=retained_tables.RetainedTableLimits(**caps)
        )
    except retained_tables.TableCatalogError as exc:
        code = "view_limit_exceeded" if exc.code == "table_limit_exceeded" else exc.code
        raise VisibleViewError(code) from None
    try:
        move_catalog = moves.read_move_catalog(
            data, source_sha256=source.sha256, limits=moves.MoveLimits(**caps)
        )
    except moves.MoveCatalogError as exc:
        code = "view_limit_exceeded" if exc.code == "move_limit_exceeded" else exc.code
        raise VisibleViewError(code) from None
    return partial(
        RetainedReader,
        catalog=move_catalog,
        table_catalog=table_catalog,
        proof_factory=proof_factory,
    )


class RetainedProperties(CurrentProperties):
    def extended(self, node, kind):
        if self.r.table_revisions.get(self.r.anchors[node]) == "inserted_" + kind:
            return
        super().extended(node, kind)


class RetainedReader(CurrentReader):
    def __init__(self, root, source, limits, *, catalog, table_catalog, proof_factory):
        super().__init__(
            root,
            source,
            limits,
            catalog=catalog,
            table_catalog=table_catalog,
            proof_factory=proof_factory,
        )
        self.table_revisions = {r.anchor: r.kind for r in table_catalog.revisions}

    def plans(self):
        for revision in self.table_catalog.revisions:
            if revision.kind == "deleted_cell":
                self.event("excluded", "deleted_table_cell", self.nodes[revision.subject_anchor])
            else:
                code = "inserted_table_" + revision.kind.removeprefix("inserted_")
                self.event("metadata", code, self.nodes[revision.anchor])
        return super().plans()

    def read_properties(self, anchor, kind):
        RetainedProperties(self).read(anchor, kind)
