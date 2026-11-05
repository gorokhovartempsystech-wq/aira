"""Internal consistency checks before using source coordinates, not authentication."""

import re
from hashlib import sha256
from uuid import UUID

from ara.docx_package.projection import SourceAnchor

from ._manifest import fragment_id, manifest_digest
from ._models import (
    PROFILE,
    AnalysisFragment,
    AnalysisSegment,
    AnalysisSnapshot,
    CoverageItem,
    SnapshotError,
)

_HASH = re.compile(r"[0-9a-f]{64}")


def is_hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def valid_identity(document_id, revision, source_hash):
    return (
        type(document_id) is UUID
        and type(revision) is int
        and 1 <= revision <= 9223372036854775807
        and is_hash(source_hash)
    )


def require(condition):
    if not condition:
        raise SnapshotError("invalid_snapshot")


def part_name(value):
    require(type(value) is str and bool(value) and len(value) <= 65535)
    require(
        "\\" not in value
        and not value.startswith("/")
        and all(piece not in ("", ".", "..") for piece in value.split("/"))
    )


def anchor(value, source_hash, part):
    require(type(value) is SourceAnchor)
    require(type(value.source_sha256) is str and value.source_sha256 == source_hash)
    require(type(value.part_name) is str and value.part_name == part)
    require(type(value.path) is tuple and 0 < len(value.path) <= 128)
    require(all(type(i) is int and i >= 0 for i in value.path))


def descendant(child, parent):
    return len(child.path) > len(parent.path) and child.path[: len(parent.path)] == parent.path


def validate_snapshot(snapshot):
    """Refuse replaced/malformed internal records without reflecting their contents."""
    try:
        _validate(snapshot)
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        raise SnapshotError("invalid_snapshot") from None


def _validate(s):
    require(type(s) is AnalysisSnapshot)
    require(valid_identity(s.document_id, s.storage_revision, s.source_sha256))
    require(type(s.extractor_version) is str and s.extractor_version == PROFILE)
    part_name(s.main_part)
    anchor(s.body_anchor, s.source_sha256, s.main_part)
    require(
        type(s.analysis_text) is str and type(s.fragments) is tuple and type(s.coverage) is tuple
    )
    require(type(s.complete) is bool and type(s.has_unprojected_content) is bool)
    require(is_hash(s.text_sha256) and is_hash(s.snapshot_sha256))
    previous_path = None
    position = 0
    by_id = {}
    for fragment in s.fragments:
        require(type(fragment) is AnalysisFragment)
        anchor(fragment.paragraph_anchor, s.source_sha256, s.main_part)
        path = fragment.paragraph_anchor.path
        require(previous_path is None or previous_path < path)
        previous_path = path
        require(
            type(fragment.fragment_id) is str
            and fragment.fragment_id == fragment_id(fragment.paragraph_anchor)
        )
        require(fragment.fragment_id not in by_id)
        by_id[fragment.fragment_id] = fragment
        require(type(fragment.text) is str and bool(fragment.text.strip()))
        require(type(fragment.analysis_start) is int and type(fragment.analysis_end) is int)
        require(
            fragment.analysis_start == position
            and fragment.analysis_end == position + len(fragment.text)
        )
        require(s.analysis_text[position : fragment.analysis_end] == fragment.text)
        position = fragment.analysis_end + 2
        require(
            type(fragment.ancestry) is tuple
            and bool(fragment.ancestry)
            and len(fragment.ancestry) % 3 == 1
            and len(fragment.ancestry) <= 127
        )
        require(fragment.ancestry[0] == s.body_anchor)
        parent = None
        for ancestor in fragment.ancestry:
            anchor(ancestor, s.source_sha256, s.main_part)
            require(parent is None or descendant(ancestor, parent))
            parent = ancestor
        require(descendant(fragment.paragraph_anchor, parent))
        require(type(fragment.segments) is tuple and bool(fragment.segments))
        segment_end = 0
        last_anchor = None
        for segment in fragment.segments:
            require(type(segment) is AnalysisSegment)
            require(type(segment.kind) is str and segment.kind in ("text", "tab", "break"))
            require(
                type(segment.start) is int
                and type(segment.end) is int
                and segment.start == segment_end < segment.end <= len(fragment.text)
            )
            anchor(segment.anchor, s.source_sha256, s.main_part)
            require(descendant(segment.anchor, fragment.paragraph_anchor))
            require(last_anchor is None or last_anchor < segment.anchor.path)
            last_anchor = segment.anchor.path
            if segment.run_anchor is not None:
                anchor(segment.run_anchor, s.source_sha256, s.main_part)
                require(
                    descendant(segment.run_anchor, fragment.paragraph_anchor)
                    and descendant(segment.anchor, segment.run_anchor)
                )
            if segment.kind != "text":
                require(
                    fragment.text[segment.start : segment.end]
                    == ("\t" if segment.kind == "tab" else "\n")
                )
            segment_end = segment.end
        require(segment_end == len(fragment.text))
    require(s.analysis_text == "\n\n".join(f.text for f in s.fragments))
    included = set()
    blocked = False
    leaf_paths = set()
    last_leaf = None
    notices_started = False
    for item in s.coverage:
        require(type(item) is CoverageItem)
        require(type(item.status) is str and item.status in ("included", "empty", "blocked"))
        require(type(item.code) is str)
        part_name(item.part_name)
        if item.anchor is not None:
            anchor(item.anchor, s.source_sha256, item.part_name)
        if item.status == "included":
            require(
                item.code == "paragraph"
                and type(item.fragment_id) is str
                and item.fragment_id in by_id
                and item.fragment_id not in included
            )
            require(item.anchor == by_id[item.fragment_id].paragraph_anchor)
            included.add(item.fragment_id)
        else:
            require(item.fragment_id is None)
        if item.status == "empty":
            require(item.code == "empty_paragraph")
        if item.status == "blocked":
            blocked = True
            require(
                item.code in ("opaque_paragraph", "opaque_block", "unprojected_content")
                or item.code
                in (
                    "notice:unsupported_element",
                    "notice:unsupported_structure",
                    "notice:tracked_change",
                    "notice:complex_field",
                    "notice:unprojected_root_element",
                    "notice:unprojected_story",
                    "notice:unprojected_part",
                )
            )
        if item.code.startswith("notice:") or item.code == "unprojected_content":
            notices_started = True
        else:
            require(
                not notices_started
                and item.anchor is not None
                and item.part_name == s.main_part
                and (
                    descendant(item.anchor, s.body_anchor)
                    or (item.code == "opaque_block" and item.anchor == s.body_anchor)
                )
            )
            require(
                item.anchor.path not in leaf_paths
                and (last_leaf is None or last_leaf < item.anchor.path)
            )
            last_leaf = item.anchor.path
            leaf_paths.add(last_leaf)
    require(included == set(by_id))
    require(not s.has_unprojected_content or blocked)
    require(s.complete == (not blocked and not s.has_unprojected_content))
    require(sha256(s.analysis_text.encode("utf-8")).hexdigest() == s.text_sha256)
    require(manifest_digest(s) == s.snapshot_sha256)
