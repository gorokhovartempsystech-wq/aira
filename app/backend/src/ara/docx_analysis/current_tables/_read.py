"""Fresh whole-source current-property proof with bounded canonical digest."""

import re
from dataclasses import replace
from hashlib import sha256

from ara.docx_analysis.tables import TableCatalogError
from ara.docx_analysis.tables._context import Blocked
from ara.docx_analysis.tables._models import budget
from ara.docx_analysis.tables._read import tokens
from ara.docx_package import DocxError, DocxLimits, open_docx

from ._context import CurrentContext
from ._geometry import CurrentGeometry
from ._models import PROFILE, CurrentTableCatalog, CurrentTableLimits
from ._parse import read_current_main


def read_current_table_catalog(data, *, source_sha256, limits=None):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise TableCatalogError("invalid_input")
    if limits is None:
        limits = CurrentTableLimits()
    if type(limits) is not CurrentTableLimits:
        raise TableCatalogError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise TableCatalogError("source_mismatch")
    source = open_docx(data)
    root = read_current_main(data, source, bounds, limits)
    tables, histories, issues = (), (), ()
    try:
        context = CurrentContext(root, source)
        geometry = CurrentGeometry(context, limits)
        tables = tuple(geometry.table(n) for n in context.tables)
        histories = tuple(context.histories)
        status = "indexed" if tables else "absent"
    except Blocked as refusal:
        tables, histories = (), ()
        status, issues = "blocked", (refusal.issue,)
    result = CurrentTableCatalog(
        source_sha256, PROFILE, status, source.main_part, tables, histories, issues, ""
    )
    size, hasher = 0, sha256()
    for token in tokens(result):
        encoded = token.encode("utf-8")
        size += len(encoded)
        budget(size, limits.max_manifest_bytes)
        hasher.update(encoded)
    return replace(result, catalog_sha256=hasher.hexdigest())
