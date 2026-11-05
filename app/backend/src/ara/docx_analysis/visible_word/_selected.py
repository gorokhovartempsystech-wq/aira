"""All original quotas precede one fixed extended MC view and source contexts."""

from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis.compatibility._models import CompatibilityCatalog, Refused
from ara.docx_analysis.compatibility._scan import scan_part
from ara.docx_analysis.compatibility._xml import preflight as mc_preflight
from ara.docx_analysis.compatibility_contexts._factories import contexts
from ara.docx_analysis.compatibility_contexts._models import (
    Blocked,
    CompatibilityContexts,
    Prepared,
)
from ara.docx_analysis.compatibility_contexts._parse import (
    compatibility_limits,
    preflight,
    table_limits,
)
from ara.docx_analysis.compatibility_contexts._read import ERRORS
from ara.docx_analysis.compatibility_view._models import PROFILE as VIEW_PROFILE
from ara.docx_analysis.compatibility_view._models import CompatibilityView
from ara.docx_analysis.compatibility_view._project import project_part
from ara.docx_analysis.sections._xml import parse
from ara.docx_analysis.table_styles._parse import Counter as StyleCounter
from ara.docx_analysis.visible_inline_images._parse import Drawings
from ara.docx_analysis.visible_main._canonical import tokens
from ara.docx_analysis.visible_main._models import VisibleViewError, budget

from ._models import CATALOG_PROFILE, CONTEXT_PROFILE, STYLE_PROFILE
from ._roles import BASE, EFFECTS, xml_parts
from ._styles import Grammar


def bounded_hash(value, limits):
    size, digest = 0, sha256()
    for token in tokens(value):
        encoded = token.encode("utf-8")
        size += len(encoded)
        budget(size, limits.max_manifest_bytes)
        digest.update(encoded)
    return digest.hexdigest()


def selected(data, source, bounds, limits):
    names, caps = xml_parts(source), compatibility_limits(limits)
    has_mc = mc_preflight(data, names, bounds, caps)
    drawings, styles = Drawings(limits), StyleCounter(table_limits(limits))
    style_parts = {
        e.name for e in source.entries if e.content_type in {BASE + "styles+xml", EFFECTS}
    }
    for name in names:
        parse(data, name, bounds, drawings)
        if name in style_parts:
            parse(data, name, bounds, styles)
    parts, issues, status = (), (), "indexed" if has_mc else "absent"
    try:
        tally = [0]
        parts = tuple(scan_part(data, name, source.sha256, bounds, caps, tally) for name in names)
    except Refused as refusal:
        status, issues = "blocked", (refusal.issue,)
    catalog = CompatibilityCatalog(
        source.sha256, CATALOG_PROFILE, status, source.main_part, parts, issues, ""
    )
    catalog = replace(catalog, catalog_sha256=bounded_hash(catalog, limits))
    if status == "blocked":
        return CompatibilityView(source.sha256, VIEW_PROFILE, "blocked", catalog, (), issues)
    try:
        projected = tuple(project_part(data, p, source.sha256, bounds) for p in parts)
        return CompatibilityView(source.sha256, VIEW_PROFILE, "ready", catalog, projected, ())
    except Refused as refusal:
        return CompatibilityView(
            source.sha256, VIEW_PROFILE, "blocked", catalog, (), (refusal.issue,)
        )


def prepare(data, source, bounds, limits):
    try:
        proof_limits = table_limits(limits)
        preflight(data, source, bounds, limits, proof_limits)
        view = selected(data, source, bounds, limits)
        try:
            result = contexts(
                data,
                source,
                view,
                limits,
                proof_limits,
                grammar_type=Grammar,
                style_profile=STYLE_PROFILE,
                context_profile=CONTEXT_PROFILE,
            )
        except Blocked as refusal:
            result = CompatibilityContexts(
                source.sha256,
                CONTEXT_PROFILE,
                "blocked",
                view.catalog.catalog_sha256,
                None,
                None,
                None,
                None,
                (refusal.issue,),
            )
        bounded_hash(result, limits)
        return Prepared(source, view, result)
    except ERRORS as exc:
        code = "view_limit_exceeded" if exc.code.endswith("limit_exceeded") else exc.code
        raise VisibleViewError(code) from None
