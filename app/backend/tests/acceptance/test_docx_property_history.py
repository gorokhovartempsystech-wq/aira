"""Frozen b2a1 acceptance: opt-in current properties, never replay old markup."""

from dataclasses import asdict, replace
from importlib import import_module

import pytest
from docx_projection_fixtures import package
from test_docx_final_view import DOC, digest, p, rehash
from test_docx_final_view import build as build_b1

PROFILE = "docx-analysis/final-properties-v1"


def api():
    return import_module("ara.docx_analysis.final_view")


def build(raw, **kwargs):
    from hashlib import sha256

    return api().build_properties_snapshot(
        raw, document_id=DOC, storage_revision=9, source_sha256=sha256(raw).hexdigest(), **kwargs
    )


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_current_text_old_properties_and_boundaries_are_independent(strict, encoding):
    body = '<w:p><w:pPr><w:rPr><w:del w:id="1"/><w:rPrChange w:id="2">'
    body += '<w:rPr><w:ins w:id="4"/></w:rPr></w:rPrChange></w:rPr>'
    body += '<w:pPrChange w:id="3"><w:pPr><w:rPr><w:ins w:id="5"/></w:rPr>'
    body += "<s:payload>HISTORICAL_PRIVATE</s:payload></w:pPr></w:pPrChange></w:pPr>"
    body += '<w:r><w:rPr><w:b/><w:rPrChange w:id="6"><w:rPr><w:vanish/>'
    body += '<w:fldSimple w:instr="DO NOT RUN"/></w:rPr></w:rPrChange></w:rPr>'
    body += "<w:t>A</w:t></w:r></w:p>" + p("B")
    raw, _ = package(body, strict=strict, encoding=encoding, main_part="custom/Properties.xml")
    result = build(raw)
    assert result.complete and result.analysis_text == "AB"
    assert result.profile == PROFILE and len(result.fragments[0].joins) == 1
    assert not build_b1(raw).complete
    records = [c for c in result.coverage if c.code == "historical_properties"]
    assert len(records) == 3 and all(c.status == "excluded" for c in records)
    f = result.fragments[0]
    mapped = api().map_final_span(result, fragment_id=f.fragment_id, start=0, end=2, quote="AB")
    assert len(mapped.slices) == 2
    assert "HISTORICAL_PRIVATE" not in repr(result) + repr(f)
    assert result == build(raw)


def test_same_bytes_new_profile_changes_ids_and_preserves_b1():
    raw = package(p("text"))[0]
    old, new = build_b1(raw), build(raw)
    assert old.complete and new.complete and old.analysis_text == new.analysis_text
    assert new.fragments[0].fragment_id != old.fragments[0].fragment_id
    assert old.snapshot_sha256 != new.snapshot_sha256
    fragment = new.fragments[0]
    value = asdict(fragment)
    expected = {
        key: value[key] for key in ("story_anchor", "flow_anchor", "paragraph_anchors", "joins")
    }
    expected.update(
        domain="docx-final-fragment/1",
        profile=PROFILE,
        policy_version=new.policy_version,
        source_sha256=new.source_sha256,
    )
    assert fragment.fragment_id == "lf-" + digest(expected)
    assert rehash(new) == new
    assert build_b1(raw) == old


@pytest.mark.parametrize(
    "history",
    [
        '<w:pPrChange w:id="1"/>',
        '<w:pPrChange w:id="1"><w:rPr/></w:pPrChange>',
        "<w:pPrChange><w:pPr/></w:pPrChange>",
        '<w:pPrChange w:id="x"><w:pPr/></w:pPrChange>',
        '<w:pPrChange w:id="1"><w:pPr/><w:pPr/></w:pPrChange>',
        '<w:pPrChange w:id="1"><s:pPr/></w:pPrChange>',
        '<w:pPrChange w:id="1"><w:pPr/></w:pPrChange>BAD',
        '<w:pPrChange w:id="1"><w:pPr/></w:pPrChange><w:pPrChange w:id="2"><w:pPr/></w:pPrChange>',
        '<w:rPrChange w:id="1"><w:rPr/></w:rPrChange>',
    ],
)
def test_malformed_or_wrong_context_history_is_not_clean_text(history):
    result = build(package("<w:p><w:pPr>" + history + "</w:pPr><w:r><w:t>A</w:t></w:r></w:p>")[0])
    assert not result.complete and result.fragments == ()


def test_old_paragraph_mark_does_not_join_and_current_hidden_still_blocked():
    body = '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr><w:rPr><w:del w:id="2"/>'
    body += "</w:rPr></w:pPr></w:pPrChange></w:pPr><w:r><w:t>A</w:t></w:r></w:p>"
    raw = package(body + p("B"))[0]
    result = build(raw)
    assert result.complete and [f.text for f in result.fragments] == ["A", "B"]
    hidden = '<w:p><w:r><w:rPr><w:vanish/><w:rPrChange w:id="1"><w:rPr/>'
    hidden += "</w:rPrChange></w:rPr><w:t>A</w:t></w:r></w:p>"
    assert not build(package(hidden)[0]).complete


def test_historical_record_corruption_cannot_rebind_source_pieces():
    raw = package(
        '<w:p><w:r><w:rPr><w:rPrChange w:id="1"><w:rPr/></w:rPrChange>'
        "</w:rPr><w:t>A</w:t></w:r></w:p>"
    )[0]
    s = build(raw)
    f = s.fragments[0]
    record = next(c for c in s.coverage if c.code == "historical_properties")
    bad_record = replace(record, anchor=f.pieces[0].anchor)
    broken = rehash(
        replace(s, coverage=tuple(bad_record if c == record else c for c in s.coverage))
    )
    with pytest.raises(api().FinalViewError) as caught:
        api().map_final_span(broken, fragment_id=f.fragment_id, start=0, end=1, quote="A")
    assert caught.value.code == "invalid_snapshot"
    old_profile = rehash(replace(s, profile="docx-analysis/final-main-v1"))
    with pytest.raises(api().FinalViewError):
        api().map_final_span(old_profile, fragment_id=f.fragment_id, start=0, end=1, quote="A")


def test_history_counts_coverage_and_excluded_subtree_input_budgets():
    raw = package(
        '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr/></w:pPrChange></w:pPr>'
        "<w:r><w:t>A</w:t></w:r></w:p>"
    )[0]
    s = build(raw)
    assert build(raw, limits=api().FinalViewLimits(max_coverage_items=len(s.coverage))) == s
    with pytest.raises(api().FinalViewError) as caught:
        build(raw, limits=api().FinalViewLimits(max_coverage_items=len(s.coverage) - 1))
    assert caught.value.code == "view_limit_exceeded"
    excluded = package(
        '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr>'
        + p("old") * 3
        + "</w:pPr></w:pPrChange></w:pPr></w:p>"
    )[0]
    with pytest.raises(api().FinalViewError) as caught:
        build(excluded, limits=api().FinalViewLimits(max_paragraphs=3))
    assert caught.value.code == "view_limit_exceeded"
