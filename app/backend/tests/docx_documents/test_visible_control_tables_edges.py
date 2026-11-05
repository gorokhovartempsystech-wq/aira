"""Structural control boundaries cannot bypass budgets, cell flows or source proof."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_control_tables import api, blocked, build, error, one
from test_docx_visible_controls import control
from test_docx_visible_fields import char, instr
from test_docx_visible_main import canonical, payload, rehash, source
from test_docx_visible_notes import literal, p


def opened(text="A"):
    return p(char("begin") + instr() + char("separate") + literal(text))


def ended(text="B"):
    return p(literal(text) + char("end"))


@pytest.mark.parametrize(
    "content",
    [
        control(opened()) + ended(),
        opened() + control(ended()),
        opened() + control() + ended(),
        opened() + control(one("Nested")) + ended(),
    ],
)
def test_fields_cannot_cross_block_controls_even_without_rendered_characters(content):
    blocked(table(row(cell(content)), columns=1))


def test_field_may_not_cross_two_individually_controlled_cells():
    body = table(row(control(cell(opened())) + control(cell(ended()))))
    blocked(body)


def test_table_control_raw_count_is_checked_before_any_dom(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw control budget")

    for name in ("sections._xml", "notes._xml", "visible_notes._parse"):
        monkeypatch.setattr(import_module("ara.docx_analysis." + name), "build_tree", forbidden)
    body = table(control(row(cell(paragraph("A")))), columns=1) * 4
    raw = source(body)[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_pieces=3)))


def test_control_wrappers_do_not_bypass_raw_table_limit(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw table budget")

    monkeypatch.setattr(import_module("ara.docx_analysis.sections._xml"), "build_tree", forbidden)
    raw = source(control(one("A")) * 1001)[0]
    error("view_limit_exceeded", lambda: build(raw))


def test_table_control_mapping_enforces_exact_manifest_and_unicode_offsets():
    raw = source(control(one("😀é")))[0]
    s = build(raw)
    assert s.complete
    f = s.fragments[0]
    m = api().map_control_table_span(raw, s, fragment_id=f.fragment_id, start=0, end=2, quote="😀e")
    assert len(m.slices) == 1 and (m.slices[0].start, m.slices[0].end) == (0, 2)
    size = len(canonical(payload(s)))
    assert build(raw, limits=api().VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=size - 1)),
    )


@pytest.mark.parametrize("empty", [False, True])
def test_mapping_rebuilds_once_and_cannot_forge_another_cell_or_old_profile(monkeypatch, empty):
    raw = source(control(table(row(cell(paragraph("A")) + control(cell(paragraph("B")))))))[0]
    s = build(raw)
    module = import_module("ara.docx_analysis.visible_control_tables._api")
    original, count = module.build_control_table_snapshot, 0

    def wrapped(*a, **kw):
        nonlocal count
        count += 1
        return original(*a, **kw)

    monkeypatch.setattr(module, "build_control_table_snapshot", wrapped)
    f = s.fragments[0]
    q = api().VisibleSpanRequest(f.fragment_id, 0, 1, "A")
    queries = () if empty else (q,) * 3
    assert (
        len(api().map_control_table_spans(raw, s, requests=queries)) == len(queries) and count == 1
    )
    forged = rehash(
        replace(s, fragments=(replace(f, flow_anchor=s.fragments[1].flow_anchor), s.fragments[1]))
    )
    error("invalid_snapshot", lambda: api().map_control_table_spans(raw, forged, requests=()))
    old = import_module("ara.docx_analysis.visible_controls")
    error("invalid_snapshot", lambda: old.map_control_spans(raw, s, requests=()))
    old_s = old.build_control_snapshot(
        raw,
        document_id=s.document_id,
        storage_revision=s.storage_revision,
        source_sha256=s.source_sha256,
    )
    assert not old_s.complete and old_s.fragments == ()


def test_hidden_payload_inside_controlled_cell_is_not_ignored_as_unknown_markup():
    unknown = "<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:drawing/></w:r></w:p>"
    blocked(table(row(control(cell(unknown))), columns=1))


def test_separate_process_table_control_reading_and_mapping_are_inert():
    raw = source(control(one("Saved")))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
from uuid import UUID
data=sys.stdin.buffer.read()
def forbidden(*a,**kw):raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.visible_control_tables import (
    build_control_table_snapshot,map_control_table_spans,VisibleSpanRequest)
s=build_control_table_snapshot(data,document_id=UUID("12345678-1234-4234-8234-123456789abc"),
    storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Saved"
f=s.fragments[0]
query=VisibleSpanRequest(f.fragment_id,0,5,"Saved")
assert len(map_control_table_spans(data,s,requests=(query,)))==1
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    settings = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
    result = subprocess.run(
        [sys.executable, "-c", script], input=raw, capture_output=True, env=settings, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode()


def test_structural_and_inline_controls_are_accounted_once_each():
    from test_docx_visible_fields import run
    from test_docx_visible_main import codes

    inline = "<w:p>" + control(run(literal("A"))) + "</w:p>"
    body = control(table(control(row(control(cell(control(inline))))), columns=1))
    s = build(source(body)[0])
    items = [c for c in s.coverage if c.code == "rich_text_control"]
    assert s.complete and s.analysis_text == "A"
    assert len(items) == len({c.anchor for c in items}) == 5
    assert ("metadata", "table_structure") in codes(s)


def test_controlled_cell_note_reference_preserves_segments_and_physical_flow():
    from test_docx_visible_notes import fixture, ref

    raw = fixture(table(row(control(cell(p(literal("A") + ref() + literal("B"))))), columns=1))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "A\n\nB\n\nFoot 🧪"
    assert len(s.references) == 1
    assert s.fragments[0].flow_anchor == s.fragments[1].flow_anchor
    assert s.references[0].before_fragment_id == s.fragments[0].fragment_id
    assert s.references[0].after_fragment_id == s.fragments[1].fragment_id


def test_new_profile_keeps_uncontrolled_table_field_reading_equivalent():
    from test_docx_visible_fields import build as field_build
    from test_docx_visible_fields import complex_field

    raw = source(table(row(cell(p(complex_field(literal("Cache"))))), columns=1))[0]
    old, new = field_build(raw), build(raw)
    assert old.complete and new.complete and old.analysis_text == new.analysis_text == "Cache"
    assert old.paragraphs == new.paragraphs and old.runs == new.runs
    assert old.fragments[0].pieces == new.fragments[0].pieces
    assert old.fragments[0].flow_anchor == new.fragments[0].flow_anchor
    assert old.profile != new.profile


def test_control_wrapper_cannot_weaken_deleted_cell_payload_proof():
    from test_docx_retained_tables import marker

    deleted = control(cell("<w:unsupported/>", marker("cellDel")))
    blocked(table(row(deleted + cell(paragraph("Kept"))), columns=1))


def test_controlled_table_does_not_infer_grid_with_unknown_gap_width():
    from test_docx_grid_tables import gridless

    body = gridless(control(row(cell(paragraph("A")), '<w:gridBefore w:val="1"/>')))
    blocked(control(body))


def test_foreign_namespace_row_wrapper_does_not_become_a_valid_control():
    foreign = '<x:sdt xmlns:x="http://purl.oclc.org/ooxml/wordprocessingml/main">'
    foreign += "<x:sdtContent>" + row(cell(paragraph("A"))) + "</x:sdtContent></x:sdt>"
    blocked(table(foreign, columns=1))
