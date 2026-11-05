"""Additional D03-17A1 invariants, including rehashed malformed DTOs."""

from dataclasses import asdict, replace
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from docx_projection_fixtures import package, paragraph
from test_docx_analysis_snapshot import build, digest

from ara.docx_analysis import SnapshotError, SnapshotLimits, build_snapshot, map_span


def rehash(snapshot):
    manifest = asdict(snapshot)
    manifest.pop("snapshot_sha256")
    manifest["document_id"] = str(snapshot.document_id)
    manifest["storage_revision"] = str(snapshot.storage_revision)
    return replace(snapshot, snapshot_sha256=digest(manifest))


def check_invalid(snapshot):
    with pytest.raises(SnapshotError) as caught:
        map_span(snapshot, fragment_id="absent", start=0, end=1, quote="x")
    assert caught.value.code == "invalid_snapshot"


@pytest.mark.parametrize(
    "change",
    [
        {"start": True},
        {"end": 0},
        {"kind": "opaque"},
        {"anchor": None},
    ],
)
def test_rehashed_bad_segment_is_rejected(change):
    snap = build(package(paragraph("abc"))[0])
    fragment = snap.fragments[0]
    segment = replace(fragment.segments[0], **change)
    check_invalid(rehash(replace(snap, fragments=(replace(fragment, segments=(segment,)),))))


@pytest.mark.parametrize(
    "change",
    [
        {"fragment_id": "absent"},
        {"status": "empty"},
        {"code": "empty_paragraph"},
        {"part_name": "other.xml"},
        {"anchor": None},
    ],
)
def test_rehashed_bad_coverage_is_rejected(change):
    snap = build(package(paragraph("abc"))[0])
    check_invalid(rehash(replace(snap, coverage=(replace(snap.coverage[0], **change),))))


def test_rehashed_anchor_outside_paragraph_and_bool_path_are_rejected():
    snap = build(package(paragraph("abc"))[0])
    fragment = snap.fragments[0]
    segment = fragment.segments[0]
    for path in ((0, 8, 0, 0), (0, False, 0, 0)):
        broken = replace(segment, anchor=replace(segment.anchor, path=path))
        check_invalid(rehash(replace(snap, fragments=(replace(fragment, segments=(broken,)),))))


@pytest.mark.parametrize(
    "body,after",
    [
        ("<w:p><w:pPr/><w:pPr/>" + "<w:r><w:t>bad</w:t></w:r></w:p>" + paragraph("ok"), ""),
        ("<w:p><w:ins><w:r><w:t>revision</w:t></w:r></w:ins></w:p>" + paragraph("ok"), ""),
        ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r></w:p>', ""),
        (paragraph("ok"), "<s:unknown/>"),
    ],
)
def test_every_projection_notice_kind_preserves_mapping_of_remaining_clean_text(body, after):
    snap = build(package(body, after_body=after)[0])
    assert not snap.complete
    if snap.fragments:
        fragment = snap.fragments[0]
        mapped = map_span(
            snap,
            fragment_id=fragment.fragment_id,
            start=0,
            end=len(fragment.text),
            quote=fragment.text,
        )
        assert mapped.paragraph_anchor == fragment.paragraph_anchor
    else:
        with pytest.raises(SnapshotError) as caught:
            map_span(snap, fragment_id="absent", start=0, end=1, quote="x")
        assert caught.value.code == "unknown_fragment"


def test_document_identity_changes_digest_but_not_fragment_ids():
    raw = package(paragraph("abc"))[0]
    snap = build(raw)
    other = build_snapshot(
        raw, document_id=uuid4(), storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert other.snapshot_sha256 != snap.snapshot_sha256
    assert other.fragments == snap.fragments
    maximum = build_snapshot(
        raw,
        document_id=UUID(int=0),
        storage_revision=2**63 - 1,
        source_sha256=sha256(raw).hexdigest(),
    )
    assert maximum.storage_revision == 2**63 - 1


def test_mutated_limits_and_unknown_snapshot_types_are_refused():
    limits = SnapshotLimits()
    object.__setattr__(limits, "max_fragments", False)
    with pytest.raises(SnapshotError) as caught:
        build(package(paragraph("abc"))[0], limits=limits)
    assert caught.value.code == "invalid_input"
    for value in (None, {}, "text"):
        check_invalid(value)


def test_all_subranges_of_mixed_unicode_map_exactly():
    raw = package(
        "<w:p><w:r><w:t>A😀</w:t><w:tab/><w:t>é</w:t></w:r><w:r><w:br/><w:t>Z</w:t></w:r></w:p>"
    )[0]
    snap = build(raw)
    fragment = snap.fragments[0]
    for start in range(len(fragment.text)):
        for end in range(start + 1, len(fragment.text) + 1):
            mapped = map_span(
                snap,
                fragment_id=fragment.fragment_id,
                start=start,
                end=end,
                quote=fragment.text[start:end],
            )
            by_anchor = {s.anchor: fragment.text[s.start : s.end] for s in fragment.segments}
            assert (
                "".join(by_anchor[s.anchor][s.start : s.end] for s in mapped.slices)
                == (fragment.text[start:end])
            )
