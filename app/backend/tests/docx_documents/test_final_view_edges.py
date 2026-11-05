"""Additional b1 grammar, rehashed graph and bounded mapping checks."""

from dataclasses import replace
from hashlib import sha256
from uuid import UUID

import pytest
from docx_projection_fixtures import package
from test_docx_final_view import build, error, p, rehash

from ara.docx_analysis import build_snapshot, inventory_docx
from ara.docx_analysis.final_view import FinalViewLimits, build_final_snapshot, map_final_span


@pytest.mark.parametrize(
    "content",
    [
        '<w:hyperlink><w:ins w:id="1"><w:hyperlink><w:r><w:t>x</w:t></w:r>'
        "</w:hyperlink></w:ins></w:hyperlink>",
        "<w:r><w:rPr/><w:rPr/><w:t>x</w:t></w:r>",
        '<w:pPr><w:rPr><w:del w:id="1"><w:ins w:id="2"/></w:del></w:rPr></w:pPr>',
        '<w:pPr><w:numPr><w:numId w:val="1"/><w:numId w:val="2"/></w:numPr></w:pPr>',
        '<w:ins w:id="not decimal"><w:r><w:t>x</w:t></w:r></w:ins>',
        "<w:r><s:t>x</s:t></w:r>",
    ],
)
def test_unsupported_context_never_leaks_neighbor_text(content):
    result = build(package(p("before") + "<w:p>" + content + "</w:p>" + p("after"))[0])
    assert not result.complete and result.fragments == ()


def test_comments_pi_properties_unicode_cr_and_external_links():
    raw, _ = package(
        '<w:p><w:pPr><w:pStyle w:val="Local"/><w:spacing w:after="0"/>'
        '<w:numPr><w:numId w:val="1"/><w:ilvl w:val="0"/></w:numPr></w:pPr>'
        '<!-- p --><?test pi?><w:hyperlink r:id="remote"><w:r><w:rPr><w:i/></w:rPr>'
        '<w:t> A<!-- t -->B&#xD;C </w:t><w:cr/><w:br w:type="page"/>'
        '<w:br w:type="column"/></w:r></w:hyperlink></w:p>'
        '<w:sectPr><w:pgSz w:w="11906"/><w:cols w:num="1"/></w:sectPr>',
        links=[
            {
                "Id": "remote",
                "Type": "urn:test",
                "Target": "https://invalid.example/",
                "TargetMode": "External",
            }
        ],
    )
    result = build(raw)
    assert result.complete and result.analysis_text == " AB\rC \n\n\n"
    f = result.fragments[0]
    assert f.paragraph_anchors[0].path == (0, 0)
    assert f.pieces[0].anchor.path == (0, 0, 1, 0, 1)
    mapped = map_final_span(
        result, fragment_id=f.fragment_id, start=0, end=len(f.text), quote=f.text
    )
    assert len(mapped.slices) == 4


@pytest.mark.parametrize(
    "change",
    [
        {"start": True},
        {"source_end": 100},
        {"anchor": None},
        {"run_anchor": None},
        {"kind": "opaque"},
    ],
)
def test_rehashed_invalid_piece_graph_is_rejected(change):
    s = build(package(p("A", "del") + p("B"))[0])
    f = s.fragments[0]
    piece = replace(f.pieces[0], **change)
    broken = rehash(replace(s, fragments=(replace(f, pieces=(piece, *f.pieces[1:])),)))
    error(
        "invalid_snapshot",
        lambda: map_final_span(broken, fragment_id=f.fragment_id, start=0, end=1, quote="A"),
    )


def test_unknown_or_malformed_snapshot_types_are_safe():
    for value in (None, {}, "text"):
        error(
            "invalid_snapshot",
            lambda: map_final_span(value, fragment_id="absent", start=0, end=1, quote="x"),
        )


def test_identity_and_empty_deleted_chains_keep_old_apis_unchanged():
    raw = package(p("", "del") + p(" ") + p("A"))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "A"
    assert sum(c.status == "empty" for c in s.coverage) == 2
    mapped = map_final_span(s, fragment_id=s.fragments[0].fragment_id, start=0, end=1, quote="A")
    assert len(mapped.slices) == 1
    other = build_final_snapshot(
        raw,
        document_id=UUID(int=2),
        storage_revision=2**63 - 1,
        source_sha256=sha256(raw).hexdigest(),
    )
    assert other.snapshot_sha256 != s.snapshot_sha256
    assert other.fragments == s.fragments
    legacy = build_snapshot(
        raw, document_id=UUID(int=2), storage_revision=1, source_sha256=sha256(raw).hexdigest()
    )
    assert not legacy.complete and legacy.extractor_version == "docx-analysis/main-body-v1"
    assert inventory_docx(raw, source_sha256=sha256(raw).hexdigest()).policy.revisions == "final"


def test_output_limit_refuses_before_return_and_mutated_limits_revalidated():
    raw = package('<w:p><w:ins w:id="1"><w:r><w:t>A</w:t></w:r></w:ins></w:p>')[0]
    # 3 parts, main flow, paragraph and inserted-content event.
    assert build(raw, limits=FinalViewLimits(max_coverage_items=6)).complete
    error("view_limit_exceeded", lambda: build(raw, limits=FinalViewLimits(max_coverage_items=5)))
    limits = FinalViewLimits()
    object.__setattr__(limits, "max_nodes", True)
    error("invalid_input", lambda: build(raw, limits=limits))


def test_many_excluded_gaps_map_without_quadratic_pairwise_search():
    content = '<w:r><w:t>A</w:t></w:r><w:del w:id="1"><s:opaque/></w:del>'
    result = build(package("<w:p>" + content * 3000 + "</w:p>")[0])
    assert result.analysis_text == "A" * 3000
    f = result.fragments[0]
    mapped = map_final_span(result, fragment_id=f.fragment_id, start=0, end=3000, quote=f.text)
    assert len(mapped.slices) == 3000
