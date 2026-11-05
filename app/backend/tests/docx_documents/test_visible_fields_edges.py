"""Raw budgets, source-backed field mapping and closed cross-flow semantics."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_note_catalog import note
from test_docx_section_catalog import section
from test_docx_visible_fields import api, build, char, complex_field, error, instr, p, run, simple
from test_docx_visible_main import canonical, payload, rehash, source
from test_docx_visible_notes import fixture, literal


def test_field_open_across_current_section_boundary_is_not_a_single_flow():
    body = (
        "<w:p><w:pPr>"
        + section()
        + "</w:pPr>"
        + run(char("begin") + instr() + char("separate") + literal("A"))
        + "</w:p>"
    )
    body += p(literal("B") + char("end"))
    s = build(source(body)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.references == ()


def test_history_and_deleted_field_markup_do_not_join_the_current_stack():
    old = '<w:del w:id="1">' + run(char("begin") + instr("OLD")) + "</w:del>"
    history = '<w:rPrChange w:id="2"><w:rPr>' + char("end") + "</w:rPr></w:rPrChange>"
    current = "<w:r><w:rPr>" + history + "</w:rPr>" + complex_field(literal("Kept")) + "</w:r>"
    s = build(source("<w:p>" + old + current + "</w:p>")[0])
    assert s.complete and s.analysis_text == "Kept"


def test_raw_unused_and_excluded_field_count_is_bounded_before_any_dom(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("DOM before extra field budget")

    for module in (
        "ara.docx_analysis.sections._xml",
        "ara.docx_analysis.notes._xml",
        "ara.docx_analysis.visible_notes._parse",
    ):
        monkeypatch.setattr(import_module(module), "build_tree", forbidden)
    raw = source('<w:p><w:del w:id="1">' + simple("") * 4 + "</w:del></w:p>")[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_pieces=3)))
    raw = fixture(p(literal("Body")), foot=note(content="<w:p>" + simple("") * 4 + "</w:p>"))[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_pieces=3)))


def test_semantic_field_nesting_is_bounded_even_when_xml_depth_is_shallow():
    raw = source(p(char("begin") * 65 + instr() + char("end") * 65))[0]
    error("view_limit_exceeded", lambda: build(raw))


def test_exact_canonical_manifest_and_unicode_mapping_of_saved_result():
    raw = source(
        p(complex_field(literal("Я😀") + "<w:tab/>" + instr("é") + "<w:br/>" + literal("Z")))
    )[0]
    s = build(raw)
    f = s.fragments[0]
    assert s.complete and f.text == "Я😀\té\nZ"
    m = api().map_field_span(raw, s, fragment_id=f.fragment_id, start=1, end=6, quote="😀\té\n")
    assert [v.kind for v in m.slices] == ["text", "tab", "text", "break"]
    assert [(v.start, v.end) for v in m.slices] == [(1, 2), (0, 1), (0, 2), (0, 1)]
    size = len(canonical(payload(s)))
    assert build(raw, limits=api().VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=size - 1)),
    )


@pytest.mark.parametrize("empty", [False, True])
def test_field_batch_rebuild_once_and_old_profile_does_not_accept_extended_grammar(
    monkeypatch, empty
):
    raw = source(p(complex_field()))[0]
    s = build(raw)
    am = import_module("ara.docx_analysis.visible_fields._api")
    count = 0
    original = am.build_field_snapshot

    def wrapped(*a, **kw):
        nonlocal count
        count += 1
        return original(*a, **kw)

    monkeypatch.setattr(am, "build_field_snapshot", wrapped)
    f = s.fragments[0]
    q = api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)
    queries = () if empty else (q,) * 4
    assert len(api().map_field_spans(raw, s, requests=queries)) == len(queries) and count == 1
    old = import_module("ara.docx_analysis.visible_notes")
    error("invalid_snapshot", lambda: old.map_note_spans(raw, s, requests=()))
    old_s = old.build_note_snapshot(
        raw,
        document_id=s.document_id,
        storage_revision=s.storage_revision,
        source_sha256=s.source_sha256,
    )
    assert not old_s.complete and old_s.fragments == ()
    error(
        "invalid_snapshot",
        lambda: api().map_field_spans(raw, rehash(replace(s, analysis_text="Forged")), requests=()),
    )


def test_fresh_process_does_not_execute_field_command_or_read_application_environment():
    raw = source("<w:p>" + simple(command="DDE shell SYSTEM") + "</w:p>")[0]
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
from ara.docx_analysis.visible_fields import build_field_snapshot,map_field_spans,VisibleSpanRequest
s=build_field_snapshot(data,document_id=UUID("12345678-1234-4234-8234-123456789abc"),storage_revision=1,
                      source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Cached"
f=s.fragments[0]
assert len(map_field_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,6,"Cached"),)))==1
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        timeout=30,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_cross_paragraph_field_inside_one_cell_keeps_both_original_paragraphs():
    from test_docx_table_catalog import cell, row, table

    content = p(char("begin") + instr("TOC") + char("separate") + literal("A"))
    content += p(literal("B") + char("end"))
    s = build(source(table(row(cell(content)), 1))[0])
    assert s.complete and s.analysis_text == "A\n\nB"
    assert len(s.fragments) == 2 and s.fragments[0].flow_anchor == s.fragments[1].flow_anchor
    assert s.fragments[0].paragraph_anchor != s.fragments[1].paragraph_anchor


def test_empty_instruction_is_not_evaluated_when_literal_cache_exists():
    s = build(source("<w:p>" + simple(command="") + "</w:p>")[0])
    assert s.complete and s.analysis_text == "Cached"


def test_deleted_invalidated_field_does_not_poison_retained_result():
    deleted = '<w:del w:id="8">' + simple(attrs=' w:dirty="true"') + "</w:del>"
    s = build(source("<w:p>" + deleted + simple(run(literal("Kept"))) + "</w:p>")[0])
    assert s.complete and s.analysis_text == "Kept"


def test_note_generated_label_inside_cached_field_keeps_reference_and_source_slice():
    from test_docx_visible_notes import ref

    content = "<w:p>" + simple(run("<w:footnoteRef/>" + literal("Note"))) + "</w:p>"
    raw = fixture(p(ref()), foot=note(content=content))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Note" and len(s.references) == 1
    assert s.references[0].target_anchor == s.fragments[0].story_anchor
    assert s.fragments[0].pieces[0].anchor.path == (0, 0, 0, 0, 1)


def test_complex_fields_do_not_pair_between_main_and_header_story():
    from test_docx_section_catalog import BASE, reference
    from test_docx_visible_main import R
    from test_docx_visible_stories import story_xml

    body = p(char("begin") + instr()) + section(reference())
    raw = source(
        body,
        links=[{"Id": "H", "Type": R + "header", "Target": "H.xml"}],
        extra_parts={
            "custom/H.xml": story_xml(p(char("separate") + literal("Text") + char("end")))
        },
        extra_types={"custom/H.xml": BASE + "header+xml"},
    )[0]
    s = build(raw)
    assert not s.complete and s.fragments == s.references == () and s.analysis_text == ""
