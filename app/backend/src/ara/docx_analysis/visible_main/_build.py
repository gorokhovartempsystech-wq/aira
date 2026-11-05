"""Derive every selector, visibility decision and source piece from pinned bytes."""

import re
from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from ara.docx_analysis.inventory import _classify
from ara.docx_analysis.visibility._read import MIME, read_style_context
from ara.docx_analysis.visibility.rules import RunVisibilityQuery, _effective
from ara.docx_package import DocxError, DocxLimits, open_docx
from ara.docx_package.projection import ProjectionError, ProjectionLimits
from ara.docx_package.projection._parse import parse_main

from ._canonical import coverage_key, digest, fragment_id
from ._models import (
    POLICY,
    PROFILE,
    VisibleCoverage,
    VisibleFragment,
    VisibleLimits,
    VisibleParagraphContext,
    VisiblePiece,
    VisibleRunContext,
    VisibleSnapshot,
    VisibleViewError,
    budget,
    checked_limits,
)
from ._parse import preflight
from ._reader import Reader, Refusal

PROPERTIES = {
    "application/vnd.openxmlformats-package.core-properties+xml",
    "application/vnd.openxmlformats-package.custom-properties+xml",
    "application/vnd.openxmlformats-officedocument.extended-properties+xml",
}


def valid_identity(document_id, revision, sha):
    return (
        type(document_id) is UUID
        and type(getattr(document_id, "int", None)) is int
        and 0 <= document_id.int < 2**128
        and type(revision) is int
        and 1 <= revision < 2**63
        and type(sha) is str
        and re.fullmatch(r"[0-9a-f]{64}", sha) is not None
    )


def paragraph_style(index, identity):
    if identity is None:
        return None
    record = index.get(identity)
    if record is None:
        raise Refusal("missing_paragraph_style")
    if record.style_type != "paragraph":
        raise Refusal("paragraph_style_type_mismatch")
    if record.status != "resolved":
        raise Refusal("unresolved_paragraph_style")
    return record.properties


def contexts(reader, plans, catalog, limits):
    index = {s.style_id: s for s in catalog.styles}
    implicit = index.get(catalog.default_character_style)
    if implicit is not None and (
        implicit.status != "resolved"
        or any(
            getattr(implicit.properties, n).value is not None
            for n in ("vanish", "spec_vanish", "web_hidden")
        )
    ):
        raise Refusal("implicit_character_style")
    paragraphs, runs, atoms = [], [], []
    for p in plans:
        anchor = reader.anchors[p.node]
        requested = reader.attr(p.selector, "val") if p.selector is not None else None
        identity = requested if requested is not None else catalog.default_paragraph_style
        props = paragraph_style(index, identity)
        for level in (catalog.defaults, props, p.mark):
            if level is not None and any(
                getattr(level, n).value is True for n in ("vanish", "spec_vanish")
            ):
                raise Refusal("unresolved_paragraph_boundary")
        paragraphs.append(
            VisibleParagraphContext(
                anchor,
                reader.anchors[p.selector] if p.selector is not None else None,
                requested,
                identity,
                p.mark,
            )
        )
        visible = []
        for r in p.runs:
            character = reader.attr(r.selector, "val") if r.selector is not None else None
            values = [
                getattr(r.properties, n).value for n in ("vanish", "spec_vanish", "web_hidden")
            ]
            decision = _effective(catalog, index, RunVisibilityQuery(requested, character, *values))
            if decision.status == "blocked":
                raise Refusal(decision.code)
            runs.append(
                VisibleRunContext(
                    reader.anchors[r.node],
                    anchor,
                    reader.anchors[r.selector] if r.selector is not None else None,
                    character,
                    character,
                    r.properties,
                    decision,
                )
            )
            if decision.hidden:
                reader.event("excluded", "hidden_run", r.node)
            else:
                visible.extend((kind, node, r.node, text) for kind, node, text in r.atoms)
        atoms.append(visible)
    return tuple(paragraphs), tuple(runs), atoms


def _main_reader(data, source, limits):
    return Reader


def build_visible_snapshot(
    data: bytes,
    *,
    document_id: UUID,
    storage_revision: int,
    source_sha256: str,
    limits: VisibleLimits | None = None,
) -> VisibleSnapshot:
    return _build_snapshot(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        prepare_reader=_main_reader,
        profile=PROFILE,
    )


def _build_snapshot(
    data,
    *,
    document_id,
    storage_revision,
    source_sha256,
    limits,
    prepare_reader,
    profile,
):
    limits = checked_limits(limits)
    if type(data) is not bytes or not valid_identity(document_id, storage_revision, source_sha256):
        raise VisibleViewError("invalid_input")
    bounds = DocxLimits()
    if len(data) > bounds.max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise VisibleViewError("source_mismatch")
    source = open_docx(data)
    preflight(data, source, limits)
    reader_factory = prepare_reader(data, source, limits)
    catalog = read_style_context(data, source_sha256=source_sha256, limits=limits.styles)
    try:
        root = parse_main(
            data, source, bounds, ProjectionLimits(limits.max_xml_nodes, limits.max_xml_depth)
        )
    except ProjectionError:
        raise VisibleViewError("view_limit_exceeded") from None
    reader = reader_factory(root, source, limits)
    body = reader.anchors[reader.body]
    failure = None
    paragraphs = runs = ()
    fragments, coverage = [], []

    def cover(status, code, anchor=None, fid=None, part=None):
        budget(len(coverage) + 1, limits.max_coverage_items)
        coverage.append(VisibleCoverage(status, code, part or source.main_part, anchor, fid))

    try:
        if catalog.status == "blocked":
            raise Refusal("style_context_blocked")
        reader.validate_style_context(catalog)
        plans = reader.plans()
        paragraphs, runs, atoms = contexts(reader, plans, catalog, limits)
    except Refusal as exc:
        failure = exc.code
        paragraphs = runs = ()
    for entry in source.entries:
        category, _ = _classify(entry.name, entry.content_type, source.main_part)
        if category == "main_body":
            status, code = "metadata", "main_part"
        elif category == "package_metadata" or entry.content_type in PROPERTIES:
            status, code = "metadata", "package_metadata"
        elif category == "comments":
            status, code = "excluded", "comments_policy"
        elif entry.content_type == MIME:
            accounted = (
                not failure and catalog.status == "ready" and entry.name == catalog.styles_part
            )
            status, code = (
                ("metadata", "style_context_accounted")
                if accounted
                else ("blocked", "style_usage_unproven")
            )
        else:
            status, code = "blocked", "unread_part"
        cover(status, code, part=entry.name)
    if failure:
        cover("blocked", failure, body)
    else:
        cover("metadata", "main_flow_read", body)
        for status, code, anchor in reader.events:
            cover(status, code, anchor)
        position = total_pieces = 0
        for p, visible in zip(paragraphs, atoms, strict=True):
            if not any(text.strip() for _, _, _, text in visible):
                cover("empty", "empty_paragraph", p.paragraph_anchor)
                continue
            length = sum(len(text) for _, _, _, text in visible)
            start = position + (2 if fragments else 0)
            budget(start + length, limits.max_text_characters)
            total_pieces += len(visible)
            budget(total_pieces, limits.max_pieces)
            pieces, texts, offset = [], [], 0
            for kind, atom, run, text in visible:
                pieces.append(
                    VisiblePiece(
                        kind,
                        reader.anchors[atom],
                        reader.anchors[run],
                        p.paragraph_anchor,
                        offset,
                        offset + len(text),
                        0,
                        len(text),
                    )
                )
                texts.append(text)
                offset += len(text)
            flow = reader.flow_anchor(p.paragraph_anchor)
            fid = fragment_id(
                body,
                p.paragraph_anchor,
                source_sha256,
                limits.max_manifest_bytes,
                profile=profile,
                flow=flow,
            )
            fragments.append(
                VisibleFragment(
                    fid,
                    body,
                    flow,
                    p.paragraph_anchor,
                    "".join(texts),
                    tuple(pieces),
                    start,
                    start + length,
                )
            )
            cover("included", "paragraph", p.paragraph_anchor, fid)
            position = start + length
    text = "\n\n".join(f.text for f in fragments)
    result = VisibleSnapshot(
        document_id,
        storage_revision,
        source_sha256,
        profile,
        POLICY,
        source.main_part,
        catalog,
        paragraphs,
        runs,
        tuple(fragments),
        text,
        tuple(sorted(coverage, key=coverage_key)),
        not any(c.status == "blocked" for c in coverage),
        sha256(text.encode()).hexdigest(),
        "",
    )
    return replace(
        result, snapshot_sha256=digest(result, limits.max_manifest_bytes, omit_hash=True)
    )
