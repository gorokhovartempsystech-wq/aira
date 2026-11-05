"""Fresh whole-source current logical-grid proof with bounded canonical digest."""

import re
from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis.retained_tables._context import RetainedContext
from ara.docx_analysis.retained_tables._parse import read_retained_main
from ara.docx_analysis.tables import TableCatalogError
from ara.docx_analysis.tables._context import Blocked
from ara.docx_analysis.tables._models import budget
from ara.docx_analysis.tables._read import tokens
from ara.docx_package import DocxError, DocxLimits, open_docx

from ._geometry import GridGeometry
from ._models import PROFILE, GridTableCatalog, GridTableLimits


def read_grid_table_catalog(data, *, source_sha256, limits=None):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise TableCatalogError("invalid_input")
    if limits is None:
        limits = GridTableLimits()
    if type(limits) is not GridTableLimits:
        raise TableCatalogError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise TableCatalogError("source_mismatch")
    source = open_docx(data)
    root = read_retained_main(data, source, bounds, limits)
    tables, histories, revisions, issues = (), (), (), ()
    try:
        context = RetainedContext(root, source)
        geometry = GridGeometry(context, limits)
        tables = tuple(geometry.table(n) for n in context.tables)
        histories = tuple(context.histories)
        revisions = tuple(context.revisions)
        status = "indexed" if tables else "absent"
    except Blocked as refusal:
        tables, histories, revisions = (), (), ()
        status, issues = "blocked", (refusal.issue,)
    result = GridTableCatalog(
        source_sha256, PROFILE, status, source.main_part, tables, histories, revisions, issues, ""
    )
    size, hasher = 0, sha256()
    for token in tokens(result):
        encoded = token.encode("utf-8")
        size += len(encoded)
        budget(size, limits.max_manifest_bytes)
        hasher.update(encoded)
    return replace(result, catalog_sha256=hasher.hexdigest())
