"""Select each table's own style from the same pinned source as its cell flows."""

from functools import partial

from ara.docx_analysis.table_styles import TableStyleError, TableStyleLimits
from ara.docx_analysis.table_styles import _read as style_proof
from ara.docx_analysis.table_styles._parse import preflight, styles_part
from ara.docx_analysis.visibility import StyleContextError
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_main._reader import Refusal, check
from ara.docx_analysis.visible_tables._reader import TableReader, read_catalogs
from ara.docx_package import DocxLimits

from ._properties import StyledProperties, conditional


def translated(exc):
    code = (
        "view_limit_exceeded"
        if exc.code in ("table_style_limit_exceeded", "style_limit_exceeded")
        else exc.code
    )
    return VisibleViewError(code)


def build_proof(data, context, *, style_limits, proof_limits):
    try:
        return style_proof.catalog(data, context, style_limits, proof_limits)
    except (TableStyleError, StyleContextError) as exc:
        raise translated(exc) from None


def prepare_styles(data, source, limits):
    proof_limits = TableStyleLimits(
        max_xml_nodes=min(limits.max_xml_nodes, limits.styles.max_nodes),
        max_xml_depth=min(limits.max_xml_depth, limits.styles.max_depth),
        max_xml_characters=limits.max_xml_characters,
        max_styles=limits.styles.max_styles,
        max_chain_depth=limits.styles.max_chain_depth,
        max_issues=limits.styles.max_issues,
        max_manifest_bytes=limits.max_manifest_bytes,
    )
    try:
        preflight(data, styles_part(source), DocxLimits(), proof_limits)
    except TableStyleError as exc:
        raise translated(exc) from None
    return partial(build_proof, data, style_limits=limits.styles, proof_limits=proof_limits)


def prepare_reader(data, source, limits):
    proof_factory = prepare_styles(data, source, limits)
    table_catalog, move_catalog = read_catalogs(data, source, limits)
    return partial(
        StyledReader,
        catalog=move_catalog,
        table_catalog=table_catalog,
        proof_factory=proof_factory,
    )


class StyledReader(TableReader):
    def __init__(self, root, source, limits, *, catalog, table_catalog, proof_factory):
        super().__init__(root, source, limits, catalog=catalog, table_catalog=table_catalog)
        self.proof_factory = proof_factory
        self.proven_selectors = set()

    def validate_style_context(self, context):
        if not self.tables:
            return
        proof = self.proof_factory(context)
        definitions = {s.style_id: s for s in proof.styles}
        all_styles = {s.style_id: s for s in context.styles}
        for table in self.table_catalog.tables:
            selector = None
            if table.properties_anchor is not None:
                properties = self.nodes[table.properties_anchor]
                selectors = [n for n in properties if self.name(n) == "tblStyle"]
                try:
                    check(len(selectors) <= 1)
                    if selectors:
                        selector = selectors[0]
                        self.selector(selector)
                except Refusal:
                    raise Refusal("unsupported_table_properties") from None
            identity = (
                self.attr(selector, "val") if selector is not None else proof.default_table_style
            )
            if identity is None:
                continue
            actual = all_styles.get(identity)
            if actual is None:
                raise Refusal("missing_table_style")
            if actual.style_type != "table":
                raise Refusal("table_style_type_mismatch")
            if definitions[identity].status != "neutral":
                raise Refusal("unresolved_table_style")
            self.event("metadata", "table_style_proven", self.nodes[table.anchor])
            if selector is not None:
                self.proven_selectors.add(self.anchors[selector])

    def read_properties(self, anchor, kind):
        StyledProperties(self).read(anchor, kind)

    def formatting_property(self, node, kind):
        if kind == "pPr" and self.name(node) == "cnfStyle":
            conditional(self, node)
        else:
            super().formatting_property(node, kind)
