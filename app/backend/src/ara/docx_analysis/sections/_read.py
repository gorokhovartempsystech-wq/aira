"""Pinned original package to bounded current section-reference metadata."""

import re
from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis.tables._read import tokens
from ara.docx_package import DocxError, DocxLimits, open_docx

from . import _xml
from ._context import Context
from ._models import PROFILE, Refused, SectionCatalog, SectionCatalogError, SectionLimits, budget
from ._resolve import inherit, settings_flag, settings_part


def read_section_catalog(data, *, source_sha256, limits=None):
    return _read_section_catalog(data, source_sha256=source_sha256, limits=limits)


def _read_section_catalog(
    data,
    *,
    source_sha256,
    limits=None,
    tree_reader=None,
    context_type=None,
    settings_reader=None,
    profile=PROFILE,
):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise SectionCatalogError("invalid_input")
    if limits is None:
        limits = SectionLimits()
    if type(limits) is not SectionLimits:
        raise SectionCatalogError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise SectionCatalogError("source_mismatch")
    source = open_docx(data)
    selected, even = None, None
    sections, stories, histories, issues = (), (), (), ()
    try:
        selected = settings_part(source)
        parts = (source.main_part, selected) if selected else (source.main_part,)
        _xml.preflight(data, parts, bounds, limits)
        trees = tree_reader or _xml.build_tree
        root = trees(data, source.main_part, bounds)
        settings = trees(data, selected, bounds) if selected else None
        context = (context_type or Context)(root, source, limits)
        even = (settings_reader or settings_flag)(settings, source, selected, context.ns)
        sections, stories = inherit(context.sections, even, source)
        histories = tuple(context.histories)
        status = "indexed"
    except Refused as refusal:
        sections, stories, histories, even = (), (), (), None
        status, issues = "blocked", (refusal.issue,)
    result = SectionCatalog(
        source_sha256,
        profile,
        status,
        source.main_part,
        selected,
        even,
        sections,
        stories,
        histories,
        issues,
        "",
    )
    size, hasher = 0, sha256()
    for token in tokens(result):
        encoded = token.encode("utf-8")
        size += len(encoded)
        budget(size, limits.max_manifest_bytes)
        hasher.update(encoded)
    return replace(result, catalog_sha256=hasher.hexdigest())
