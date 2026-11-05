"""Public source-pinned factory with aggregate preflight and bounded serialization."""

import re
from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis.tables._read import tokens
from ara.docx_package import DocxError, DocxLimits, open_docx

from . import _xml
from ._definitions import candidates, linked_parts, read_part
from ._models import PROFILE, NoteCatalog, NoteCatalogError, NoteLimits, Refused, budget


def read_note_catalog(data, *, source_sha256, limits=None):
    return _read_note_catalog(data, source_sha256=source_sha256, limits=limits)


def _read_note_catalog(
    data, *, source_sha256, limits=None, tree_reader=None, part_reader=None, profile=PROFILE
):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise NoteCatalogError("invalid_input")
    if limits is None:
        limits = NoteLimits()
    if type(limits) is not NoteLimits:
        raise NoteCatalogError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise NoteCatalogError("source_mismatch")
    source = open_docx(data)
    selected = candidates(source)
    ordered = tuple(sorted(selected))
    _xml.preflight(data, ordered, bounds, limits)
    parts, issues = (), ()
    try:
        linked = linked_parts(source, selected)
        parts = tuple(
            (part_reader or read_part)(
                (tree_reader or _xml.build_tree)(data, name, bounds),
                name,
                selected[name],
                name in linked,
                source_sha256,
            )
            for name in ordered
        )
        status = "indexed" if parts else "absent"
    except Refused as refusal:
        parts, status, issues = (), "blocked", (refusal.issue,)
    result = NoteCatalog(source_sha256, profile, status, source.main_part, parts, issues, "")
    size, hasher = 0, sha256()
    for token in tokens(result):
        encoded = token.encode("utf-8")
        size += len(encoded)
        budget(size, limits.max_manifest_bytes)
        hasher.update(encoded)
    return replace(result, catalog_sha256=hasher.hexdigest())
