"""Account derived logical columns at their real table while preserving cell flows."""

from functools import partial

from ara.docx_analysis import grid_tables, moves
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_retained_tables._reader import RetainedReader
from ara.docx_analysis.visible_styled_tables._reader import prepare_styles


def prepare_reader(data, source, limits):
    proof_factory = prepare_styles(data, source, limits)
    caps = dict(
        max_xml_nodes=limits.max_xml_nodes,
        max_xml_depth=limits.max_xml_depth,
        max_xml_characters=limits.max_xml_characters,
    )
    try:
        table_catalog = grid_tables.read_grid_table_catalog(
            data, source_sha256=source.sha256, limits=grid_tables.GridTableLimits(**caps)
        )
    except grid_tables.TableCatalogError as exc:
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
        GridReader,
        catalog=move_catalog,
        table_catalog=table_catalog,
        proof_factory=proof_factory,
    )


class GridReader(RetainedReader):
    def grid_event(self, table):
        if table.grid_anchor is not None:
            super().grid_event(table)
        if table.grid_mode != "explicit":
            self.event("metadata", "derived_table_grid", self.nodes[table.anchor])
