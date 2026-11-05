"""Read current cell flows without rewriting stored property histories."""

from functools import partial

from ara.docx_analysis import current_tables, moves
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_styled_tables._properties import StyledProperties
from ara.docx_analysis.visible_styled_tables._reader import StyledReader, prepare_styles


def prepare_reader(data, source, limits):
    proof_factory = prepare_styles(data, source, limits)
    caps = dict(
        max_xml_nodes=limits.max_xml_nodes,
        max_xml_depth=limits.max_xml_depth,
        max_xml_characters=limits.max_xml_characters,
    )
    try:
        table_catalog = current_tables.read_current_table_catalog(
            data, source_sha256=source.sha256, limits=current_tables.CurrentTableLimits(**caps)
        )
    except current_tables.TableCatalogError as exc:
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
        CurrentReader,
        catalog=move_catalog,
        table_catalog=table_catalog,
        proof_factory=proof_factory,
    )


class CurrentProperties(StyledProperties):
    def extended(self, node, kind):
        if self.r.histories.get(self.r.anchors[node]) == kind:
            return
        super().extended(node, kind)


class CurrentReader(StyledReader):
    def __init__(self, root, source, limits, *, catalog, table_catalog, proof_factory):
        super().__init__(
            root,
            source,
            limits,
            catalog=catalog,
            table_catalog=table_catalog,
            proof_factory=proof_factory,
        )
        self.histories = {h.anchor: h.kind for h in table_catalog.histories}

    def plans(self):
        for history in self.table_catalog.histories:
            code = (
                "historical_table_grid" if history.kind == "grid" else "historical_table_properties"
            )
            self.event("excluded", code, self.nodes[history.anchor])
        return super().plans()

    def read_properties(self, anchor, kind):
        CurrentProperties(self).read(anchor, kind)
