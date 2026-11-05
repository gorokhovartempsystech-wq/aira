"""Pinned-source catalog with complete raw preflight and atomic semantic decisions."""

import re
from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis.tables._read import tokens
from ara.docx_package import DocxError, DocxLimits, open_docx

from . import _scan, _xml
from ._models import (
    PROFILE,
    CompatibilityCatalog,
    CompatibilityCatalogError,
    CompatibilityLimits,
    Refused,
    budget,
)


def read_compatibility_catalog(data, *, source_sha256, limits=None):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise CompatibilityCatalogError("invalid_input")
    if limits is None:
        limits = CompatibilityLimits()
    if type(limits) is not CompatibilityLimits:
        raise CompatibilityCatalogError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise CompatibilityCatalogError("source_mismatch")
    source = open_docx(data)
    selected = _xml.candidates(source)
    has_mc = _xml.preflight(data, selected, bounds, limits)
    parts, issues = (), ()
    try:
        tally = [0]
        parts = tuple(
            _scan.scan_part(data, part, source_sha256, bounds, limits, tally) for part in selected
        )
        status = "indexed" if has_mc else "absent"
    except Refused as refusal:
        parts, status, issues = (), "blocked", (refusal.issue,)
    result = CompatibilityCatalog(
        source_sha256, PROFILE, status, source.main_part, parts, issues, ""
    )
    size, hasher = 0, sha256()
    for token in tokens(result):
        encoded = token.encode("utf-8")
        size += len(encoded)
        budget(size, limits.max_manifest_bytes)
        hasher.update(encoded)
    return replace(result, catalog_sha256=hasher.hexdigest())
