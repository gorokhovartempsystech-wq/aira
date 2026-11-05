"""Validate source bytes, recognize the whole flow, then emit bounded output."""

from dataclasses import replace
from hashlib import sha256
from uuid import UUID

from ara.docx_analysis._validate import valid_identity
from ara.docx_analysis.inventory import _classify
from ara.docx_package import DocxError, DocxLimits, open_docx
from ara.docx_package.projection import ProjectionLimits
from ara.docx_package.projection._parse import parse_main

from ._manifest import coverage_key, fragment_id, manifest_digest
from ._models import (
    POLICY,
    PROFILE,
    FinalCoverage,
    FinalFragment,
    FinalPiece,
    FinalSnapshot,
    FinalViewError,
    FinalViewLimits,
    ParagraphJoin,
)
from ._reader import Reader, Unsupported

_PROPERTIES = frozenset(
    (
        "application/vnd.openxmlformats-package.core-properties+xml",
        "application/vnd.openxmlformats-package.custom-properties+xml",
        "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    )
)


def budget(count, maximum):
    if count > maximum:
        raise FinalViewError("view_limit_exceeded")


def build_final_snapshot(
    data: bytes,
    *,
    document_id: UUID,
    storage_revision: int,
    source_sha256: str,
    limits: FinalViewLimits | None = None,
) -> FinalSnapshot:
    return _build_snapshot(
        data,
        document_id=document_id,
        storage_revision=storage_revision,
        source_sha256=source_sha256,
        limits=limits,
        profile=PROFILE,
        reader_type=Reader,
    )


def _build_snapshot(
    data,
    *,
    document_id,
    storage_revision,
    source_sha256,
    limits,
    profile,
    reader_type,
):
    if type(data) is not bytes or not valid_identity(document_id, storage_revision, source_sha256):
        raise FinalViewError("invalid_input")
    if limits is None:
        limits = FinalViewLimits()
    if type(limits) is not FinalViewLimits:
        raise FinalViewError("invalid_input")
    limits.__post_init__()
    if len(data) > DocxLimits().max_archive_bytes:
        raise DocxError("package_limit_exceeded")
    if sha256(data).hexdigest() != source_sha256:
        raise FinalViewError("source_mismatch")
    source = open_docx(data)
    root = parse_main(
        data, source, DocxLimits(), ProjectionLimits(limits.max_nodes, limits.max_depth)
    )
    reader = reader_type(root, source)
    budget(sum(reader.name(n) == "p" for n in root.iter()), limits.max_paragraphs)
    coverage = []

    def cover(status, code, anchor=None, fid=None, part=None):
        budget(len(coverage) + 1, limits.max_coverage_items)
        coverage.append(FinalCoverage(status, code, part or source.main_part, anchor, fid))

    for entry in source.entries:
        category, _ = _classify(entry.name, entry.content_type, source.main_part)
        if category == "main_body":
            status, code = "metadata", "main_part"
        elif category == "package_metadata" or entry.content_type in _PROPERTIES:
            status, code = "metadata", "package_metadata"
        elif category == "comments":
            status, code = "excluded", "comments_policy"
        else:
            status, code = "blocked", "unread_part"
        cover(status, code, part=entry.name)
    fragments = []
    try:
        plans = reader.plans()
    except Unsupported:
        cover("blocked", "unsupported_main_flow", reader.anchors[reader.body])
    else:
        body = reader.anchors[reader.body]
        cover("metadata", "main_flow_read", body)
        for status, code, anchor in reader.events:
            cover(status, code, anchor)
        characters = piece_count = 0
        group = []
        for plan in plans:
            group.append(plan)
            if plan.marker is not None:
                continue
            # Empty groups consume input budgets but create no final text or pieces.
            nonempty = any(text.strip() for p in group for _, _, _, text in p.atoms)
            if not nonempty:
                for p in group:
                    cover("empty", "empty_paragraph", reader.anchors[p.node])
                group = []
                continue
            budget(len(fragments) + 1, limits.max_fragments)
            atom_count = sum(len(p.atoms) for p in group)
            budget(piece_count + atom_count, limits.max_pieces)
            length = sum(len(text) for p in group for _, _, _, text in p.atoms)
            start = characters + (2 if fragments else 0)
            budget(start + length, limits.max_text_characters)
            pieces = []
            position = 0
            for p in group:
                for kind, atom, run, text in p.atoms:
                    pieces.append(
                        FinalPiece(
                            kind,
                            reader.anchors[atom],
                            reader.anchors[run],
                            reader.anchors[p.node],
                            position,
                            position + len(text),
                            0,
                            len(text),
                        )
                    )
                    position += len(text)
            joins = tuple(
                ParagraphJoin(
                    reader.anchors[left.node],
                    reader.anchors[right.node],
                    reader.anchors[left.marker],
                )
                for left, right in zip(group, group[1:])
            )
            fragment = FinalFragment(
                "",
                body,
                body,
                tuple(reader.anchors[p.node] for p in group),
                "".join(t for p in group for _, _, _, t in p.atoms),
                tuple(pieces),
                joins,
                start,
                start + length,
            )
            fragment = replace(
                fragment, fragment_id=fragment_id(fragment, source_sha256, profile=profile)
            )
            fragments.append(fragment)
            for p in group:
                cover("included", "paragraph", reader.anchors[p.node], fragment.fragment_id)
            characters = start + length
            piece_count += atom_count
            group = []
    text = "\n\n".join(f.text for f in fragments)
    result = FinalSnapshot(
        document_id,
        storage_revision,
        source_sha256,
        profile,
        POLICY,
        source.main_part,
        tuple(fragments),
        text,
        tuple(sorted(coverage, key=coverage_key)),
        not any(c.status == "blocked" for c in coverage),
        sha256(text.encode("utf-8")).hexdigest(),
        "",
    )
    return replace(result, snapshot_sha256=manifest_digest(result))
