"""Fresh pinned-source factory, exact old style context and bounded proof digest."""

import json
import re
from dataclasses import fields, is_dataclass, replace
from hashlib import sha256

from ara.docx_analysis import visibility
from ara.docx_analysis.visibility._parse import parse
from ara.docx_package import DocxError, DocxLimits, open_docx
from ara.docx_package.projection import SourceAnchor

from ._graph import resolve
from ._models import (
    PROFILE,
    TableStyleCatalog,
    TableStyleError,
    TableStyleIssue,
    TableStyleLimits,
    budget,
)
from ._parse import preflight, styles_part
from ._proof import Proof


def tokens(value):
    if is_dataclass(value):
        yield "{"
        for i, name in enumerate(
            sorted(f.name for f in fields(value) if f.name != "catalog_sha256")
        ):
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
        yield json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def catalog(data, context, caps, limits, *, tree_reader=None, proof_type=None, profile=PROFILE):
    styles, issues, default = (), (), None
    inherited_issues = len(context.issues) + sum(len(s.issues) for s in context.styles)
    budget(inherited_issues, limits.max_issues)
    if context.status == "blocked":
        anchor = (
            SourceAnchor(context.source_sha256, context.styles_part, ())
            if context.styles_part
            else None
        )
        status, issues = "blocked", (TableStyleIssue("style_context_blocked", anchor, None),)
    elif context.styles_part is not None:
        root = (tree_reader or parse)(data, context.styles_part, caps)
        proof = (proof_type or Proof)(root, context.source_sha256, context.styles_part)
        nodes = {anchor: node for node, anchor in proof.anchors.items()}
        all_styles = {s.style_id: s for s in context.styles}
        definitions = {
            s.style_id: proof.own(s, nodes[s.anchor])
            for s in context.styles
            if s.style_type == "table"
        }
        styles = resolve(definitions, all_styles, limits, inherited_issues)
        default = next((s.style_id for s in styles if s.is_default), None)
        status = "ready" if styles else "absent"
    else:
        status = "absent"
    budget(inherited_issues + len(issues), limits.max_issues)
    result = TableStyleCatalog(
        context.source_sha256,
        profile,
        status,
        context.styles_part,
        context.context_sha256,
        default,
        styles,
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


def read_table_style_catalog(data, *, source_sha256, limits=None):
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise TableStyleError("invalid_input")
    if limits is None:
        limits = TableStyleLimits()
    if type(limits) is not TableStyleLimits:
        raise TableStyleError("invalid_input")
    limits.__post_init__()
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise TableStyleError("source_mismatch")
    source = open_docx(data)
    preflight(data, styles_part(source), bounds, limits)
    caps = visibility.StyleContextLimits(
        max_nodes=limits.max_xml_nodes,
        max_depth=limits.max_xml_depth,
        max_styles=limits.max_styles,
        max_chain_depth=limits.max_chain_depth,
        max_issues=limits.max_issues,
    )
    try:
        context = visibility.read_style_context(data, source_sha256=source_sha256, limits=caps)
        return catalog(data, context, caps, limits)
    except visibility.StyleContextError as exc:
        code = "table_style_limit_exceeded" if exc.code == "style_limit_exceeded" else exc.code
        raise TableStyleError(code) from None
