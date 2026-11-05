"""Resolve a styles relationship, without external templates or application I/O."""

import json
import re
from dataclasses import asdict, replace
from functools import partial
from hashlib import sha256

from ara.docx_package import DocxError, DocxLimits, open_docx
from ara.docx_package._xml import WORD_NAMESPACES
from ara.docx_package.projection import SourceAnchor

from ._grammar import Grammar, Unsupported
from ._graph import resolve
from ._models import (
    PROFILE,
    StyleContext,
    StyleContextError,
    StyleContextLimits,
    StyleIssue,
    absent,
)
from ._parse import parse

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
REL_TYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/styles",
}


def context(
    sha,
    status,
    part=None,
    defaults=None,
    default_ids=None,
    styles=(),
    code=None,
    *,
    profile=PROFILE,
):
    issue = (StyleIssue(code, SourceAnchor(sha, part, ()) if part else None, None),) if code else ()
    default_ids = default_ids or {}
    result = StyleContext(
        sha,
        profile,
        status,
        part,
        defaults,
        default_ids.get("paragraph"),
        default_ids.get("character"),
        styles,
        issue,
        "",
    )
    payload = asdict(result)
    payload.pop("context_sha256")
    digest = sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return replace(result, context_sha256=digest)


def read_style_context(
    data: bytes,
    *,
    source_sha256: str,
    limits: StyleContextLimits | None = None,
) -> StyleContext:
    return _read_style_context(data, source_sha256=source_sha256, limits=limits)


def _read_style_context(
    data, *, source_sha256, limits=None, tree_reader=None, grammar_type=None, profile=PROFILE
):
    make_context = partial(context, profile=profile)
    if (
        type(data) is not bytes
        or type(source_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
    ):
        raise StyleContextError("invalid_input")
    if limits is None:
        limits = StyleContextLimits()
    if type(limits) is not StyleContextLimits:
        raise StyleContextError("invalid_input")
    limits.__post_init__()
    if len(data) > DocxLimits().max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise StyleContextError("source_mismatch")
    source = open_docx(data)
    candidates = {e.name for e in source.entries if e.content_type == MIME}
    links = [
        r
        for r in source.relationships
        if r.source_part == source.main_part and r.relationship_type in REL_TYPES
    ]
    if not candidates and not links:
        return make_context(source_sha256, "absent", defaults=absent())
    if (
        len(candidates) != 1
        or len(links) != 1
        or links[0].target_mode != "Internal"
        or links[0].resolved_part not in candidates
    ):
        return make_context(source_sha256, "blocked", code="ambiguous_styles_part")
    part = links[0].resolved_part
    root = (tree_reader or parse)(data, part, limits)
    if root.tag not in {f"{{{n}}}styles" for n in WORD_NAMESPACES}:
        return make_context(source_sha256, "blocked", part, code="unsupported_style_structure")
    grammar = (grammar_type or Grammar)(root, source_sha256, part)
    try:
        children = grammar.envelope()
    except Unsupported:
        return make_context(source_sha256, "blocked", part, code="unsupported_style_structure")
    try:
        definitions, default_ids, duplicate = grammar.identities(children)
    except Unsupported:
        return make_context(source_sha256, "blocked", part, code="invalid_style_identity")
    if duplicate:
        return make_context(source_sha256, "blocked", part, code="duplicate_default_style")
    defaults = absent()
    try:
        for node in children:
            if grammar.name(node) == "docDefaults":
                defaults = grammar.defaults(node)
    except Unsupported:
        return make_context(source_sha256, "blocked", part, code="unsupported_defaults")
    try:
        for node in children:
            if grammar.name(node) == "latentStyles":
                grammar.latent(node)
    except Unsupported:
        return make_context(source_sha256, "blocked", part, code="unsupported_style_structure")
    for d, node in definitions.values():
        grammar.definition(d, node)
    styles = resolve({key: d for key, (d, _) in definitions.items()}, limits)
    return make_context(source_sha256, "ready", part, defaults, default_ids, styles)
