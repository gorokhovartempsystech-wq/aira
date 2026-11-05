"""Final retained table text maps back across physically stored deleted cells."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_retained_tables import cell, fixture, marker, paragraph, row, source, table
from test_docx_visible_main import DOC, canonical, codes, payload, rehash


def api():
    return import_module("ara.docx_analysis.visible_retained_tables")


def build(raw, **kwargs):
    identity = dict(document_id=DOC, storage_revision=9, source_sha256=sha256(raw).hexdigest())
    return api().build_retained_table_snapshot(raw, **(identity | kwargs))


def request(f):
    return api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_literal_retained_text_paths_flows_and_exclusion_coverage(strict, encoding):
    raw, xml = fixture(strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.profile == "docx-analysis/final-visible-retained-tables-v1"
    assert s.analysis_text == "Before\n\nA\n\nB\n\nC\n\nD\n\nAfter"
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    assert {
        ("metadata", "inserted_table_row"),
        ("metadata", "inserted_table_cell"),
        ("excluded", "deleted_table_cell"),
        ("excluded", "historical_table_properties"),
    } <= codes(s)
    deleted = [c for c in s.coverage if c.code == "deleted_table_cell"]
    assert len(deleted) == 1 and deleted[0].anchor.path == (0, 1, 2, 2)
    assert [f.flow_anchor.path for f in s.fragments] == [
        (0,),
        (0, 1, 2, 1),
        (0, 1, 2, 3),
        (0, 1, 3, 0),
        (0, 1, 3, 1),
        (0,),
    ]
    mapped = api().map_retained_table_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    assert [m.slices[0].anchor.path for m in mapped] == [
        (0, 0, 0, 0),
        (0, 1, 2, 1, 1, 0, 0),
        (0, 1, 2, 3, 0, 0, 0),
        (0, 1, 3, 0, 0, 0, 0),
        (0, 1, 3, 1, 0, 0, 0),
        (0, 2, 0, 0),
    ]
    root = ET.fromstring(xml)
    assert [resolve(root, m.slices[0].anchor).text for m in mapped] == [
        "Before",
        "A",
        "B",
        "C",
        "D",
        "After",
    ]
    f = s.fragments[2]
    assert (
        api().map_retained_table_span(raw, s, fragment_id=f.fragment_id, start=0, end=1, quote="B")
        == mapped[2]
    )
    assert sha256(raw).hexdigest() == s.source_sha256 and "PRIVATE" not in repr(s)
    assert build(raw) == s


def test_inserted_structure_does_not_override_inline_deletion_or_hidden_runs():
    p = '<w:p><w:del w:id="2"><w:r><w:delText>OLD</w:delText></w:r></w:del>'
    p += '<w:ins w:id="3"><w:r><w:t>New</w:t></w:r></w:ins>'
    p += "<w:r><w:rPr><w:vanish/></w:rPr><w:t>PRIVATE</w:t></w:r></w:p>"
    raw = source(table(row(cell(p, marker("cellIns")), marker("ins")), 1))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "New"
    assert ("excluded", "hidden_run") in codes(s)
    assert len(api().map_retained_table_spans(raw, s, requests=(request(s.fragments[0]),))) == 1


def test_unresolved_retained_content_and_unread_parts_are_not_hidden_by_other_deleted_cells():
    deleted = cell(paragraph("PRIVATE"), marker("cellDel"))
    raw = source(table(row(deleted + cell("<w:p><w:unknown/></w:p>")), 1))[0]
    s = build(raw)
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    raw = source(
        table(row(deleted + cell(paragraph("A"))), 1), extra_parts={"custom/other.xml": b"<data/>"}
    )[0]
    s = build(raw)
    assert not s.complete and ("blocked", "unread_part") in codes(s)


def test_old_snapshot_foreign_profile_forged_coverage_and_deleted_only_change_rejected():
    raw = fixture()[0]
    s = build(raw)
    changed = fixture(old_text="CHANGED DELETED TEXT")[0]
    assert build(changed).analysis_text == s.analysis_text
    error("source_mismatch", lambda: api().map_retained_table_spans(changed, s, requests=()))
    old = import_module("ara.docx_analysis.visible_current_tables")
    identity = dict(document_id=DOC, storage_revision=9, source_sha256=sha256(raw).hexdigest())
    previous = old.build_current_table_snapshot(raw, **identity)
    assert not previous.complete
    error("invalid_snapshot", lambda: old.map_current_table_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_retained_table_spans(raw, previous, requests=()))
    error(
        "invalid_snapshot",
        lambda: old.map_current_table_spans(
            raw, rehash(replace(s, profile=previous.profile)), requests=()
        ),
    )
    forged = rehash(
        replace(s, coverage=tuple(c for c in s.coverage if c.code != "deleted_table_cell"))
    )
    error("invalid_snapshot", lambda: api().map_retained_table_spans(raw, forged, requests=()))
    assert api().map_retained_table_spans(raw, s, requests=()) == ()


def test_one_fresh_catalog_move_style_context_and_proof_per_batch(monkeypatch):
    raw = fixture()[0]
    s = build(raw)
    targets = [
        ("ara.docx_analysis.retained_tables", "read_retained_table_catalog"),
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
    assert (
        len(api().map_retained_table_spans(raw, s, requests=(request(s.fragments[1]),) * 17)) == 17
    )
    assert counts == [1, 1, 1, 1]
