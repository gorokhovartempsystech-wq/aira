"""Final table text reads current formatting without deleting historical source XML."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_current_tables import cell, fixture, history, paragraph, row, source, table
from test_docx_move_catalog import resolve
from test_docx_visible_main import DOC, canonical, codes, payload, rehash
from test_docx_visible_styled_tables import table_style

PROFILE = "docx-analysis/final-visible-current-tables-v1"


def api():
    return import_module("ara.docx_analysis.visible_current_tables")


def build(raw, **kwargs):
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    return api().build_current_table_snapshot(raw, **(identity | kwargs))


def request(f):
    return api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


def definitions():
    return table_style("Good") + table_style("Bad", "<w:rPr><w:vanish/></w:rPr>")


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_current_text_literal_paths_coverage_and_mapping(strict, encoding):
    raw, xml = fixture(styles=definitions(), strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.analysis_text == "Before\n\nA\n\nB\n\nAfter"
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    assert [f.flow_anchor.path for f in s.fragments] == [(0,), (0, 1, 2, 1), (0, 1, 2, 2), (0,)]
    markers = [
        (c.code, c.anchor.path) for c in s.coverage if c.code.startswith("historical_table_")
    ]
    assert sorted(markers) == sorted(
        [
            ("historical_table_properties", (0, 1, 0, 1)),
            ("historical_table_grid", (0, 1, 1, 2)),
            ("historical_table_properties", (0, 1, 2, 0, 1)),
            ("historical_table_properties", (0, 1, 2, 1, 0, 1)),
        ]
    )
    result = api().map_current_table_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    assert [m.slices[0].anchor.path for m in result] == [
        (0, 0, 0, 0),
        (0, 1, 2, 1, 1, 0, 0),
        (0, 1, 2, 2, 0, 0, 0),
        (0, 2, 0, 0),
    ]
    root = ET.fromstring(xml)
    assert [resolve(root, m.slices[0].anchor).text for m in result] == ["Before", "A", "B", "After"]
    f = s.fragments[1]
    assert (
        api().map_current_table_span(raw, s, fragment_id=f.fragment_id, start=0, end=1, quote="A")
        == result[1]
    )
    assert build(raw) == s and sha256(raw).hexdigest() == s.source_sha256


def test_missing_current_selector_uses_default_not_historical_style():
    raw = source(
        table(properties=history("table", '<w:tblStyle w:val="Missing"/>')),
        table_style("Good", default=True),
    )[0]
    s = build(raw)
    assert s.complete and len(s.fragments) == 4
    assert ("metadata", "table_style_proven") in codes(s)


@pytest.mark.parametrize(
    "kind,props,old,code",
    [
        (
            "table",
            '<w:tblStyle w:val="Bad"/>',
            '<w:tblStyle w:val="Good"/>',
            "unresolved_table_style",
        ),
        ("row", "<w:hidden/>", '<w:hidden w:val="false"/>', "unresolved_hidden_row"),
        ("cell", "<w:unknown/>", '<w:tcW w:w="1"/>', "unsupported_table_properties"),
    ],
)
def test_previous_safe_values_never_repair_unresolved_current_properties(kind, props, old, code):
    values = props + history(kind, old)
    if kind == "table":
        body = table(properties=values)
    elif kind == "row":
        body = table(row(properties=values))
    else:
        body = table(row(cell(properties=values)), 1)
    s = build(source(paragraph("Prefix") + body, definitions())[0])
    assert not s.complete and s.fragments == s.runs == s.paragraphs == () and s.analysis_text == ""
    assert ("blocked", code) in codes(s)


def test_hidden_runs_and_current_vertical_continuation_keep_original_gap_paths():
    p = "<w:p><w:r><w:t>a</w:t></w:r><w:r><w:rPr><w:vanish/></w:rPr><w:t>SECRET</w:t>"
    p += "</w:r><w:r><w:t>b</w:t></w:r></w:p>"
    rows = row(cell(p, '<w:vMerge w:val="restart"/>' + history("cell", '<w:cellDel w:id="1"/>')))
    rows += row(cell("<w:p/>", "<w:vMerge/>" + history("cell", '<w:vMerge w:val="restart"/>')))
    raw, xml = source(table(rows, 1), table_style("Good", default=True))
    s = build(raw)
    assert s.complete and s.analysis_text == "ab" and len(s.fragments) == 1
    assert {("excluded", "hidden_run"), ("excluded", "merged_cell_continuation")} <= codes(s)
    mapped = api().map_current_table_spans(raw, s, requests=(request(s.fragments[0]),))[0]
    root = ET.fromstring(xml)
    assert [resolve(root, x.anchor).text for x in mapped.slices] == ["a", "b"]
    assert "SECRET" not in repr(s)


def test_legacy_profile_still_blocks_history_and_mappers_rebuild_even_empty_batch():
    old = import_module("ara.docx_analysis.visible_styled_tables")
    raw = fixture(styles=definitions())[0]
    s = build(raw)
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    previous = old.build_styled_table_snapshot(raw, **identity)
    assert not previous.complete and ("blocked", "table_catalog_blocked") in codes(previous)
    assert api().map_current_table_spans(raw, s, requests=()) == ()
    error("invalid_snapshot", lambda: old.map_styled_table_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_current_table_spans(raw, previous, requests=()))
    error(
        "invalid_snapshot",
        lambda: old.map_styled_table_spans(
            raw, rehash(replace(s, profile=previous.profile)), requests=()
        ),
    )
    forged = rehash(
        replace(
            s, coverage=tuple(c for c in s.coverage if not c.code.startswith("historical_table_"))
        )
    )
    error("invalid_snapshot", lambda: api().map_current_table_spans(raw, forged, requests=()))


def test_unread_parts_and_current_structural_row_deletion_never_disappear():
    raw = source(table(properties=history("table")), extra_parts={"custom/other.xml": b"<data/>"})[
        0
    ]
    s = build(raw)
    assert not s.complete and ("blocked", "unread_part") in codes(s)
    body = table(
        row(
            cell(paragraph("Not automatically deleted")),
            properties='<w:del w:id="1"/>' + history("row"),
        ),
        1,
    )
    s = build(source(body)[0])
    assert not s.complete and s.fragments == () and ("blocked", "table_catalog_blocked") in codes(s)


def test_one_current_catalog_move_context_and_style_proof_per_batch(monkeypatch):
    raw = fixture(styles=definitions())[0]
    s = build(raw)
    targets = [
        ("ara.docx_analysis.current_tables", "read_current_table_catalog"),
        ("ara.docx_analysis.moves", "read_move_catalog"),
        ("ara.docx_analysis.visible_main._build", "read_style_context"),
        ("ara.docx_analysis.table_styles._read", "catalog"),
    ]
    counts = [0] * len(targets)
    for i, (module_name, name) in enumerate(targets):
        module = import_module(module_name)
        original = getattr(module, name)

        def counted(*args, _i=i, _original=original, **kwargs):
            counts[_i] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, counted)
    assert (
        len(api().map_current_table_spans(raw, s, requests=(request(s.fragments[0]),) * 15)) == 15
    )
    assert counts == [1, 1, 1, 1]


def test_historical_move_marker_cannot_authorize_current_text_or_bypass_move_guards():
    previous = '<w:moveTo w:id="1"><w:r><w:t>OLD MOVE</w:t></w:r></w:moveTo>'
    raw = source(table(properties=history("table", previous)))[0]
    s = build(raw)
    assert not s.complete and s.fragments == () and s.analysis_text == ""
    assert ("blocked", "move_catalog_blocked") in codes(s)
