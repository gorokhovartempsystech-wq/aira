"""Source validation, aggregate preflight, one view, then atomic metadata proof."""

import re
from hashlib import sha256

from ara.docx_analysis.compatibility import CompatibilityCatalogError
from ara.docx_analysis.compatibility_view import build_compatibility_view
from ara.docx_analysis.notes import NoteCatalogError
from ara.docx_analysis.sections import SectionCatalogError
from ara.docx_analysis.table_styles import TableStyleError
from ara.docx_analysis.visibility import StyleContextError
from ara.docx_analysis.visible_main._canonical import tokens
from ara.docx_analysis.visible_main._models import VisibleViewError, budget, checked_limits
from ara.docx_package import DocxError, DocxLimits, open_docx

from ._factories import contexts
from ._models import PROFILE, Blocked, CompatibilityContexts, Prepared
from ._parse import compatibility_limits, preflight, table_limits

ERRORS = (
    CompatibilityCatalogError,
    NoteCatalogError,
    SectionCatalogError,
    TableStyleError,
    StyleContextError,
)


def prepare(data, *, source_sha256, limits=None, context_factory=None, context_profile=PROFILE):
    limits = checked_limits(limits)
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise VisibleViewError("invalid_input")
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise VisibleViewError("source_mismatch")
    source = open_docx(data)
    try:
        proof_limits = table_limits(limits)
        preflight(data, source, bounds, limits, proof_limits)
        view = build_compatibility_view(
            data,
            source_sha256=source_sha256,
            limits=compatibility_limits(limits),
        )
        try:
            factory = contexts if context_factory is None else context_factory
            result = factory(data, source, view, limits, proof_limits)
        except Blocked as refusal:
            result = CompatibilityContexts(
                source_sha256,
                context_profile,
                "blocked",
                view.catalog.catalog_sha256,
                None,
                None,
                None,
                None,
                (refusal.issue,),
            )
    except ERRORS as exc:
        code = "view_limit_exceeded" if exc.code.endswith("limit_exceeded") else exc.code
        raise VisibleViewError(code) from None
    size = 0
    for token in tokens(result):
        size += len(token.encode("utf-8"))
        budget(size, limits.max_manifest_bytes)
    return Prepared(source, view, result)


def read_compatibility_contexts(data, *, source_sha256, limits=None):
    return prepare(data, source_sha256=source_sha256, limits=limits).contexts
