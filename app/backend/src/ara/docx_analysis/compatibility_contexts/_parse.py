"""All original semantic quotas precede the selected view's first DOM allocation."""

from ara.docx_analysis.compatibility import CompatibilityLimits
from ara.docx_analysis.sections import SectionLimits
from ara.docx_analysis.sections._xml import Counter as SectionCounter
from ara.docx_analysis.sections._xml import parse
from ara.docx_analysis.table_styles import TableStyleLimits
from ara.docx_analysis.table_styles._parse import Counter as StyleCounter
from ara.docx_analysis.visibility._read import MIME as STYLES_MIME
from ara.docx_analysis.visible_controls._parse import preflight as controls_preflight
from ara.docx_analysis.visible_notes._parse import preflight as notes_preflight
from ara.docx_analysis.visible_stories._parse import SETTINGS_MIME, caps


def table_limits(limits):
    return TableStyleLimits(
        max_xml_nodes=min(limits.max_xml_nodes, limits.styles.max_nodes),
        max_xml_depth=min(limits.max_xml_depth, limits.styles.max_depth),
        max_xml_characters=limits.max_xml_characters,
        max_styles=limits.styles.max_styles,
        max_chain_depth=limits.styles.max_chain_depth,
        max_issues=limits.styles.max_issues,
        max_manifest_bytes=limits.max_manifest_bytes,
    )


def compatibility_limits(limits):
    return CompatibilityLimits(
        **caps(limits),
        max_actions=min(10000, limits.max_coverage_items),
        max_mc_items=min(10000, limits.max_pieces),
        max_manifest_bytes=limits.max_manifest_bytes,
    )


def preflight(data, source, bounds, limits, proof_limits):
    notes_preflight(data, source, bounds, limits)
    controls_preflight(data, source, bounds, limits)
    styles = StyleCounter(proof_limits)
    for entry in source.entries:
        if entry.content_type == STYLES_MIME:
            parse(data, entry.name, bounds, styles)
    parts = {source.main_part} | {e.name for e in source.entries if e.content_type == SETTINGS_MIME}
    sections = SectionCounter(SectionLimits(**caps(limits)))
    for part in sorted(parts):
        parse(data, part, bounds, sections)
