"""Pinned-source structural factory with bounded canonical serialization."""

import json
import re
from dataclasses import fields, is_dataclass, replace
from hashlib import sha256

from ara.docx_package import DocxError, DocxLimits, open_docx

from ._context import Blocked, Context
from ._geometry import Geometry
from ._models import PROFILE, TableCatalog, TableCatalogError, TableLimits, budget
from ._parse import read_main


def tokens(value):
    if is_dataclass(value):
        yield "{"
        names = sorted(f.name for f in fields(value) if f.name != "catalog_sha256")
        for i, name in enumerate(names):
            if i:
                yield ","
            yield json.dumps(name)
            yield ":"
            yield from tokens(getattr(value, name))
        yield "}"
    elif type(value) is tuple:
        yield "["
        for i, child in enumerate(value):
            if i:
                yield ","
            yield from tokens(child)
        yield "]"
    else:
        yield json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def read_table_catalog(data, *, source_sha256, limits=None):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise TableCatalogError("invalid_input")
    if limits is None:
        limits = TableLimits()
    if type(limits) is not TableLimits:
        raise TableCatalogError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise TableCatalogError("source_mismatch")
    source = open_docx(data)
    root = read_main(data, source, bounds, limits)
    tables, issues = (), ()
    try:
        context = Context(root, source)
        geometry = Geometry(context, limits)
        tables = tuple(geometry.table(n) for n in context.tables)
        status = "indexed" if tables else "absent"
    except Blocked as refusal:
        status, issues = "blocked", (refusal.issue,)
    result = TableCatalog(source_sha256, PROFILE, status, source.main_part, tables, issues, "")
    size, hasher = 0, sha256()
    for token in tokens(result):
        encoded = token.encode("utf-8")
        size += len(encoded)
        budget(size, limits.max_manifest_bytes)
        hasher.update(encoded)
    return replace(result, catalog_sha256=hasher.hexdigest())
