"""Build a deterministic structural catalog from the exact supplied package bytes."""

import json
import re
from dataclasses import asdict, replace
from hashlib import sha256

from ara.docx_package import DocxError, DocxLimits, open_docx

from ._index import Blocked, index
from ._models import PROFILE, MoveCatalog, MoveCatalogError, MoveLimits
from ._parse import read_main


def read_move_catalog(data, *, source_sha256, limits=None):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise MoveCatalogError("invalid_input")
    if limits is None:
        limits = MoveLimits()
    if type(limits) is not MoveLimits:
        raise MoveCatalogError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise MoveCatalogError("source_mismatch")
    source = open_docx(data)
    root = read_main(data, source, bounds, limits)
    pairs, issues = (), ()
    try:
        pairs = index(root, source)
        status = "indexed" if pairs else "absent"
    except Blocked as refusal:
        status, issues = "blocked", (refusal.issue,)
    catalog = MoveCatalog(source_sha256, PROFILE, status, source.main_part, pairs, issues, "")
    payload = asdict(catalog)
    payload.pop("catalog_sha256")
    digest = sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    return replace(catalog, catalog_sha256=digest)
