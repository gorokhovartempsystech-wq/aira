"""Inferred grid is metadata at a real table, never synthesized source text."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_grid_tables import cell, fixture, gridless, paragraph, row, source
from test_docx_move_catalog import resolve
from test_docx_visible_main import DOC, canonical, codes, payload, rehash


def api():
    return import_module("ara.docx_analysis.visible_grid_tables")


def build(raw, **kwargs):
    identity = dict(document_id=DOC, storage_revision=11, source_sha256=sha256(raw).hexdigest())
    return api().build_grid_table_snapshot(raw, **(identity | kwargs))


def request(f):
    return api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("mode", ["omitted", "empty", "short", "exact"])
def test_regular_grid_modes_keep_original_cell_and_text_paths(mode):
    raw, xml = fixture(mode)
    s = build(raw)
    assert s.complete and s.profile == "docx-analysis/final-visible-grid-tables-v1"
    assert s.analysis_text == "A\n\nB\n\nC\n\nD"
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    derived = [c for c in s.coverage if c.code == "derived_table_grid"]
    assert len(derived) == (0 if mode == "exact" else 1)
    assert all(c.status == "metadata" and c.anchor.path == (0, 0) for c in derived)
    assert (("metadata", "table_grid") in codes(s)) == (mode != "omitted")
    offset = 0 if mode == "omitted" else 1
    flows = [(0, 0, offset, 0), (0, 0, offset, 1), (0, 0, offset + 1, 0), (0, 0, offset + 1, 1)]
    assert [f.flow_anchor.path for f in s.fragments] == flows
    mapped = api().map_grid_table_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    assert [m.slices[0].anchor.path for m in mapped] == [a + (0, 0, 0) for a in flows]
    root = ET.fromstring(xml)
    assert [resolve(root, m.slices[0].anchor).text for m in mapped] == ["A", "B", "C", "D"]
    f = s.fragments[1]
    assert (
        api().map_grid_table_span(raw, s, fragment_id=f.fragment_id, start=0, end=1, quote="B")
        == mapped[1]
    )
    assert build(raw) == s and sha256(raw).hexdigest() == s.source_sha256


def test_inferred_grid_keeps_canonical_merged_origin_once():
    rows = row(cell(paragraph("Origin"), '<w:gridSpan w:val="3"/><w:vMerge w:val="restart"/>'))
    rows += row(cell("<w:p/>", '<w:gridSpan w:val="3"/><w:vMerge/>'))
    s = build(source(gridless(rows), strict=True, encoding="utf-16")[0])
    assert s.complete and s.analysis_text == "Origin" and len(s.fragments) == 1
    assert ("excluded", "merged_cell_continuation") in codes(s)


def test_derived_grid_does_not_bypass_unknown_properties_or_unread_parts():
    raw = source(gridless(row(cell(properties="<w:unknown/>"))))[0]
    s = build(raw)
    assert (
        not s.complete
        and s.fragments == ()
        and ("blocked", "unsupported_table_properties") in codes(s)
    )
    raw = source(gridless(row(cell())), extra_parts={"custom/other.xml": b"<data/>"})[0]
    assert ("blocked", "unread_part") in codes(build(raw))


def test_source_profile_and_derived_coverage_are_authoritatively_rebuilt():
    raw = fixture()[0]
    s = build(raw)
    old = import_module("ara.docx_analysis.visible_retained_tables")
    previous = old.build_retained_table_snapshot(
        raw, document_id=DOC, storage_revision=11, source_sha256=sha256(raw).hexdigest()
    )
    assert not previous.complete
    error("invalid_snapshot", lambda: old.map_retained_table_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_grid_table_spans(raw, previous, requests=()))
    error(
        "invalid_snapshot",
        lambda: old.map_retained_table_spans(
            raw, rehash(replace(s, profile=previous.profile)), requests=()
        ),
    )
    forged = rehash(
        replace(s, coverage=tuple(c for c in s.coverage if c.code != "derived_table_grid"))
    )
    error("invalid_snapshot", lambda: api().map_grid_table_spans(raw, forged, requests=()))
    changed = fixture("empty")[0]
    assert build(changed).analysis_text == s.analysis_text
    error("source_mismatch", lambda: api().map_grid_table_spans(changed, s, requests=()))
    assert api().map_grid_table_spans(raw, s, requests=()) == ()


def test_one_catalog_move_context_and_proof_per_mapping_batch(monkeypatch):
    raw = fixture()[0]
    s = build(raw)
    targets = [
        ("ara.docx_analysis.grid_tables", "read_grid_table_catalog"),
        ("ara.docx_analysis.moves", "read_move_catalog"),
        ("ara.docx_analysis.visible_main._build", "read_style_context"),
        ("ara.docx_analysis.table_styles._read", "catalog"),
    ]
    counts = [0] * 4
    for i, (module_name, name) in enumerate(targets):
        module = import_module(module_name)
        original = getattr(module, name)

        def counted(*a, _i=i, _original=original, **kw):
            counts[_i] += 1
            return _original(*a, **kw)

        monkeypatch.setattr(module, name, counted)
    assert len(api().map_grid_table_spans(raw, s, requests=(request(s.fragments[0]),) * 13)) == 13
    assert counts == [1, 1, 1, 1]
