"""Strict internal consistency checks followed by exact, disjoint source mapping."""

import re
from hashlib import sha256

from ara.docx_analysis._validate import valid_identity
from ara.docx_package.projection import SourceAnchor

from ._manifest import coverage_key, manifest_digest
from ._manifest import fragment_id as make_id
from ._models import (
    POLICY,
    PROFILE,
    FinalCoverage,
    FinalFragment,
    FinalMappedSpan,
    FinalPiece,
    FinalSnapshot,
    FinalSourceSlice,
    FinalViewError,
    FinalViewLimits,
    ParagraphJoin,
)
from ._properties_reader import PROPERTIES_PROFILE


def require(value):
    if not value:
        raise FinalViewError("invalid_snapshot")


def hash_string(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def part(value):
    require(type(value) is str and 0 < len(value) <= 65535)
    require("\\" not in value and all(p not in ("", ".", "..") for p in value.split("/")))


def anchor(value, snapshot, part_name=None):
    require(type(value) is SourceAnchor)
    require(type(value.source_sha256) is str and value.source_sha256 == snapshot.source_sha256)
    require(type(value.part_name) is str and value.part_name == (part_name or snapshot.main_part))
    require(type(value.path) is tuple and 0 < len(value.path) <= 128)
    require(all(type(i) is int and i >= 0 for i in value.path))


def beneath(child, parent):
    return len(child.path) > len(parent.path) and child.path[: len(parent.path)] == parent.path


def validate_snapshot(snapshot):
    try:
        _validate(snapshot)
    except (AttributeError, ValueError, TypeError, OverflowError, RecursionError):
        raise FinalViewError("invalid_snapshot") from None


def _validate(s):
    maxima = FinalViewLimits()
    require(type(s) is FinalSnapshot)
    require(valid_identity(s.document_id, s.storage_revision, s.source_sha256))
    require(
        type(s.profile) is str
        and s.profile in (PROFILE, PROPERTIES_PROFILE)
        and type(s.policy_version) is str
        and s.policy_version == POLICY
    )
    part(s.main_part)
    require(
        type(s.complete) is bool
        and type(s.analysis_text) is str
        and len(s.analysis_text) <= maxima.max_text_characters
    )
    require(hash_string(s.text_sha256) and hash_string(s.snapshot_sha256))
    require(type(s.fragments) is tuple and len(s.fragments) <= maxima.max_fragments)
    require(type(s.coverage) is tuple and len(s.coverage) <= maxima.max_coverage_items)
    by_id = {}
    paragraphs = {}
    joins = set()
    position = pieces_count = physical_count = 0
    body = None
    previous_p = None
    for f in s.fragments:
        require(type(f) is FinalFragment)
        require(type(f.fragment_id) is str and f.fragment_id not in by_id)
        anchor(f.story_anchor, s)
        anchor(f.flow_anchor, s)
        require(f.story_anchor == f.flow_anchor and len(f.flow_anchor.path) == 1)
        require(body is None or body == f.flow_anchor)
        body = f.flow_anchor
        require(type(f.paragraph_anchors) is tuple and bool(f.paragraph_anchors))
        physical_count += len(f.paragraph_anchors)
        require(physical_count <= maxima.max_paragraphs)
        for p in f.paragraph_anchors:
            anchor(p, s)
            require(len(p.path) == 2 and p.path[:-1] == body.path)
            require(previous_p is None or previous_p < p.path)
            previous_p = p.path
            require(p not in paragraphs)
            paragraphs[p] = f.fragment_id
        require(type(f.joins) is tuple and len(f.joins) == len(f.paragraph_anchors) - 1)
        for index, j in enumerate(f.joins):
            require(type(j) is ParagraphJoin)
            for a in (j.left, j.right, j.marker):
                anchor(a, s)
            require((j.left, j.right) == f.paragraph_anchors[index : index + 2])
            require(j.right.path == (*j.left.path[:-1], j.left.path[-1] + 1))
            require(
                len(j.marker.path) == len(j.left.path) + 3
                and j.marker.path[:-3] == j.left.path
                and j.marker.path[-3] == 0
            )
            require(j.marker not in joins)
            joins.add(j.marker)
        require(type(f.text) is str and bool(f.text.strip()))
        require(
            type(f.analysis_start) is int
            and type(f.analysis_end) is int
            and f.analysis_start == position
            and f.analysis_end == position + len(f.text)
        )
        require(s.analysis_text[position : f.analysis_end] == f.text)
        position = f.analysis_end + 2
        require(type(f.pieces) is tuple and bool(f.pieces))
        pieces_count += len(f.pieces)
        require(pieces_count <= maxima.max_pieces)
        end = 0
        last_atom = None
        paragraph_set = set(f.paragraph_anchors)
        for piece in f.pieces:
            require(type(piece) is FinalPiece)
            for a in (piece.anchor, piece.run_anchor, piece.paragraph_anchor):
                anchor(a, s)
            require(
                piece.paragraph_anchor in paragraph_set
                and beneath(piece.run_anchor, piece.paragraph_anchor)
            )
            require(
                len(piece.anchor.path) == len(piece.run_anchor.path) + 1
                and piece.anchor.path[:-1] == piece.run_anchor.path
            )
            require(last_atom is None or last_atom < piece.anchor.path)
            last_atom = piece.anchor.path
            require(type(piece.kind) is str and piece.kind in ("text", "tab", "break"))
            require(
                all(
                    type(n) is int
                    for n in (piece.start, piece.end, piece.source_start, piece.source_end)
                )
            )
            require(
                piece.start == end < piece.end <= len(f.text)
                and piece.source_start == 0
                and piece.source_end == piece.end - piece.start
            )
            if piece.kind != "text":
                require(f.text[piece.start : piece.end] == ("\t" if piece.kind == "tab" else "\n"))
            end = piece.end
        require(end == len(f.text))
        require(f.fragment_id == make_id(f, s.source_sha256, profile=s.profile))
        by_id[f.fragment_id] = f
    require(s.analysis_text == "\n\n".join(f.text for f in s.fragments))
    body = _coverage(s, paragraphs, joins, body)
    # A piece must never be inside an explicitly excluded source subtree.
    deleted = {
        c.anchor.path for c in s.coverage if c.code in ("deleted_content", "historical_properties")
    }
    for f in s.fragments:
        for piece in f.pieces:
            require(
                not any(
                    piece.anchor.path[:depth] in deleted
                    for depth in range(1, len(piece.anchor.path) + 1)
                )
            )
    require(sha256(s.analysis_text.encode("utf-8")).hexdigest() == s.text_sha256)
    require(manifest_digest(s) == s.snapshot_sha256)


def _coverage(s, paragraphs, joins, body):
    codes = {
        "main_part": "metadata",
        "package_metadata": "metadata",
        "comments_policy": "excluded",
        "unread_part": "blocked",
        "main_flow_read": "metadata",
        "paragraph": "included",
        "empty_paragraph": "empty",
        "inserted_content": "metadata",
        "deleted_content": "excluded",
        "inserted_boundary": "metadata",
        "deleted_boundary": "excluded",
        "supported_properties": "metadata",
        "bookmark": "metadata",
        "unsupported_main_flow": "blocked",
    }
    if s.profile == PROPERTIES_PROFILE:
        codes["historical_properties"] = "excluded"
    parts = {}
    physical = {}
    boundaries = {}
    seen = set()
    flow_records = []
    excluded_joins = set()
    for c in s.coverage:
        require(type(c) is FinalCoverage and type(c.code) is str and c.code in codes)
        require(type(c.status) is str and c.status == codes[c.code])
        part(c.part_name)
        require(c not in seen)
        seen.add(c)
        if c.code == "paragraph":
            require(type(c.fragment_id) is str and paragraphs.get(c.anchor) == c.fragment_id)
        else:
            require(c.fragment_id is None)
        if c.anchor is None:
            require(
                c.part_name not in parts
                and c.code in ("main_part", "package_metadata", "comments_policy", "unread_part")
            )
            parts[c.part_name] = c
            require((c.code == "main_part") == (c.part_name == s.main_part))
            continue
        anchor(c.anchor, s, c.part_name)
        require(c.part_name == s.main_part)
        if c.code in ("main_flow_read", "unsupported_main_flow"):
            require(len(c.anchor.path) == 1 and (body is None or body == c.anchor))
            body = c.anchor
            flow_records.append(c)
        elif c.code in ("paragraph", "empty_paragraph"):
            require(c.anchor not in physical)
            physical[c.anchor] = c.fragment_id
        else:
            require(c.code not in ("main_part", "package_metadata", "unread_part"))
        if c.code in ("inserted_boundary", "deleted_boundary"):
            require(len(c.anchor.path) == 5 and c.anchor.path[-3] == 0)
            p_path = c.anchor.path[:-3]
            require(p_path not in boundaries)
            boundaries[p_path] = c
            if c.code == "deleted_boundary":
                excluded_joins.add(c.anchor)
    require(3 <= len(parts) <= 4096 and s.main_part in parts)
    require(len(flow_records) == 1)
    property_roots = {c.anchor.path for c in s.coverage if c.code == "supported_properties"}
    physical_paths = {p.path for p in physical}
    for c in s.coverage:
        if c.code == "historical_properties":
            require(c.anchor.path[:-1] in property_roots and c.anchor.path[:2] in physical_paths)
    if flow_records[0].code == "unsupported_main_flow":
        require(not s.fragments and sum(c.anchor is not None for c in s.coverage) == 1)
    else:
        require(len(physical) <= FinalViewLimits().max_paragraphs)
        ordered = sorted(physical, key=lambda a: a.path)
        require([p.path for p in ordered] == [body.path + (i,) for i in range(len(ordered))])
        require({p: fid for p, fid in physical.items() if fid is not None} == paragraphs)
        physical_by_path = {p.path: fid for p, fid in physical.items()}
        for path, c in boundaries.items():
            require(path in physical_by_path)
            if c.code == "deleted_boundary":
                successor = path[:-1] + (path[-1] + 1,)
                require(
                    successor in physical_by_path
                    and physical_by_path[path] == physical_by_path[successor]
                )
                require((c.anchor in joins) == (physical_by_path[path] is not None))
        require(joins <= excluded_joins)
        for c in s.coverage:
            if c.anchor is not None and c not in flow_records:
                require(beneath(c.anchor, body))
    require(s.complete == (not any(c.status == "blocked" for c in s.coverage)))
    require(s.coverage == tuple(sorted(s.coverage, key=coverage_key)))
    return body


def map_final_span(snapshot, *, fragment_id, start, end, quote):
    validate_snapshot(snapshot)
    if type(fragment_id) is not str or type(quote) is not str:
        raise FinalViewError("invalid_span")
    f = next((f for f in snapshot.fragments if f.fragment_id == fragment_id), None)
    if f is None:
        raise FinalViewError("unknown_fragment")
    if (
        type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(f.text)
        or f.text[start:end] != quote
    ):
        raise FinalViewError("invalid_span")
    slices = []
    for piece in f.pieces:
        a, b = max(start, piece.start), min(end, piece.end)
        if a < b:
            slices.append(
                FinalSourceSlice(
                    piece.kind,
                    piece.anchor,
                    piece.run_anchor,
                    piece.paragraph_anchor,
                    piece.source_start + a - piece.start,
                    piece.source_start + b - piece.start,
                )
            )
    return FinalMappedSpan(fragment_id, start, end, tuple(slices))
