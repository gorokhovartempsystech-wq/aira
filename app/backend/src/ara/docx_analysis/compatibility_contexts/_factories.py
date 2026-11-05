"""Reuse existing metadata algorithms over the one freshly selected view."""

from ara.docx_analysis.notes import NoteLimits
from ara.docx_analysis.notes._read import _read_note_catalog
from ara.docx_analysis.sections import SectionLimits
from ara.docx_analysis.sections._read import _read_section_catalog
from ara.docx_analysis.table_styles._read import catalog as table_catalog
from ara.docx_analysis.visibility._read import _read_style_context
from ara.docx_analysis.visible_stories._parse import caps
from ara.docx_package._xml import WORD_NAMESPACES

from ._anchors import SourceGrammar, SourceProof, SourceSections, selected_notes, selected_settings
from ._models import (
    NOTE_PROFILE,
    PROFILE,
    SECTION_PROFILE,
    STYLE_PROFILE,
    TABLE_PROFILE,
    Blocked,
    CompatibilityContexts,
    refuse_catalog,
)


def contexts(
    data,
    source,
    view,
    limits,
    proof_limits,
    *,
    grammar_type=SourceGrammar,
    style_profile=STYLE_PROFILE,
    context_profile=PROFILE,
):
    refuse_catalog(view, "compatibility_view_blocked")
    roots = {p.part_name: p.root for p in view.parts}
    root = roots[source.main_part]
    namespace = root.tag.rpartition("}")[0] + "}"
    bodies = [n for n in root if n.tag in {"{" + ns + "}body" for ns in WORD_NAMESPACES}]
    if (
        root.tag not in {"{" + ns + "}document" for ns in WORD_NAMESPACES}
        or len(bodies) != 1
        or bodies[0].tag != namespace + "body"
    ):
        raise Blocked("invalid_compatibility_main_root", root.anchor)

    def trees(data, part, bounds):
        return roots[part]

    styles = _read_style_context(
        data,
        source_sha256=source.sha256,
        limits=limits.styles,
        tree_reader=trees,
        grammar_type=grammar_type,
        profile=style_profile,
    )
    refuse_catalog(styles, "style_context_blocked")
    tables = table_catalog(
        data,
        styles,
        limits.styles,
        proof_limits,
        tree_reader=trees,
        proof_type=SourceProof,
        profile=TABLE_PROFILE,
    )
    refuse_catalog(tables, "table_style_context_blocked")
    sections = _read_section_catalog(
        data,
        source_sha256=source.sha256,
        limits=SectionLimits(**caps(limits), max_manifest_bytes=limits.max_manifest_bytes),
        tree_reader=trees,
        context_type=SourceSections,
        settings_reader=selected_settings,
        profile=SECTION_PROFILE,
    )
    refuse_catalog(sections, "section_catalog_blocked")
    notes = _read_note_catalog(
        data,
        source_sha256=source.sha256,
        limits=NoteLimits(**caps(limits), max_manifest_bytes=limits.max_manifest_bytes),
        tree_reader=trees,
        part_reader=selected_notes,
        profile=NOTE_PROFILE,
    )
    refuse_catalog(notes, "note_catalog_blocked")
    return CompatibilityContexts(
        source.sha256,
        context_profile,
        "ready",
        view.catalog.catalog_sha256,
        styles,
        tables,
        sections,
        notes,
        (),
    )
