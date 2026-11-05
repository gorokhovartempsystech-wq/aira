"""Whole-source bounds and exact mapping for saved rich-text content controls."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_note_catalog import note
from test_docx_visible_controls import api, build, control, error
from test_docx_visible_fields import run
from test_docx_visible_main import canonical, payload, rehash, source
from test_docx_visible_notes import fixture, literal, p, ref


def test_control_limits_include_unused_and_deleted_branches_before_any_dom(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw control budget")

    for name in ("sections._xml", "notes._xml", "visible_notes._parse"):
        monkeypatch.setattr(import_module("ara.docx_analysis." + name), "build_tree", forbidden)
    raw = source('<w:p><w:del w:id="1">' + control("") * 4 + "</w:del></w:p>")[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_pieces=3)))
    raw = fixture(p(literal("Main")), foot=note(content=control("") * 4))[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_pieces=3)))
    nested = ""
    for _ in range(33):
        nested = control(nested)
    error("view_limit_exceeded", lambda: build(source(nested)[0]))


def test_controls_do_not_bypass_raw_field_counter(monkeypatch):
    from test_docx_visible_fields import simple

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw field budget")

    monkeypatch.setattr(import_module("ara.docx_analysis.sections._xml"), "build_tree", forbidden)
    raw = source(control("<w:p>" + simple("") * 4 + "</w:p>"))[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_pieces=3)))


def test_unicode_source_mapping_and_exact_manifest_bound():
    raw = source(
        "<w:p>"
        + control(run(literal("Я😀") + "<w:tab/>" + literal("é") + "<w:br/>" + literal("Z")))
        + "</w:p>"
    )[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Я😀\té\nZ"
    f = s.fragments[0]
    m = api().map_control_span(raw, s, fragment_id=f.fragment_id, start=1, end=6, quote="😀\té\n")
    assert [v.kind for v in m.slices] == ["text", "tab", "text", "break"]
    assert [(v.start, v.end) for v in m.slices] == [(1, 2), (0, 1), (0, 2), (0, 1)]
    size = len(canonical(payload(s)))
    assert build(raw, limits=api().VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=size - 1)),
    )


@pytest.mark.parametrize("empty", [False, True])
def test_control_mapping_rebuilds_once_and_old_profiles_stay_closed(monkeypatch, empty):
    raw = source(control(p(literal("A"))))[0]
    s = build(raw)
    module = import_module("ara.docx_analysis.visible_controls._api")
    original, count = module.build_control_snapshot, 0

    def wrapped(*a, **kw):
        nonlocal count
        count += 1
        return original(*a, **kw)

    monkeypatch.setattr(module, "build_control_snapshot", wrapped)
    f = s.fragments[0]
    query = api().VisibleSpanRequest(f.fragment_id, 0, 1, "A")
    queries = () if empty else (query,) * 3
    assert len(api().map_control_spans(raw, s, requests=queries)) == len(queries) and count == 1
    old = import_module("ara.docx_analysis.visible_fields")
    error("invalid_snapshot", lambda: old.map_field_spans(raw, s, requests=()))
    old_s = old.build_field_snapshot(
        raw,
        document_id=s.document_id,
        storage_revision=s.storage_revision,
        source_sha256=s.source_sha256,
    )
    assert not old_s.complete and old_s.fragments == ()
    error(
        "invalid_snapshot",
        lambda: api().map_control_spans(
            raw, rehash(replace(s, analysis_text="Forged")), requests=()
        ),
    )


def test_note_markers_inside_controls_keep_segment_links_without_display_numbers():
    content = control(run(literal("Before") + ref() + literal("After")))
    s = build(fixture("<w:p>" + content + "</w:p>")[0])
    assert s.complete and s.analysis_text == "Before\n\nAfter\n\nFoot 🧪"
    link = s.references[0]
    assert link.before_fragment_id == s.fragments[0].fragment_id
    assert link.after_fragment_id == s.fragments[1].fragment_id
    assert link.target_anchor == s.fragments[2].story_anchor


def test_fresh_process_does_not_fetch_control_metadata_or_read_environment():
    raw = source(
        control(p(literal("Saved")), '<w:alias w:val="https://invalid.example/private"/>')
    )[0]
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
from ara.docx_analysis.visible_controls import (
    build_control_snapshot,map_control_spans,VisibleSpanRequest)
s=build_control_snapshot(data,document_id=UUID("12345678-1234-4234-8234-123456789abc"),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Saved"
f=s.fragments[0]
assert len(map_control_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,5,"Saved"),)))==1
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    settings = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
    result = subprocess.run(
        [sys.executable, "-c", script], input=raw, capture_output=True, env=settings, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode()


def test_maximum_supported_nested_controls_have_original_mapping():
    content = p(literal("Deep"))
    for _ in range(32):
        content = control(content)
    raw = source(content)[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Deep" and len(s.fragments) == 1
    f = s.fragments[0]
    mapped = api().map_control_span(raw, s, fragment_id=f.fragment_id, start=0, end=4, quote="Deep")
    assert mapped.slices[0].anchor.path == (0,) + (0, 0) * 32 + (0, 0, 0)


def test_empty_control_does_not_allow_an_open_field_to_cross_boundary():
    from test_docx_visible_controls import blocked
    from test_docx_visible_fields import char, instr

    blocked("<w:p>" + run(char("begin") + instr()) + control() + run(char("end")) + "</w:p>")


def test_control_inside_hyperlink_preserves_link_nesting_rules():
    contents = control(run(literal("Link")))
    raw = source('<w:p><w:hyperlink w:anchor="bookmark">' + contents + "</w:hyperlink></w:p>")[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Link"
    nested = control('<w:hyperlink w:anchor="nested">' + run(literal("N")) + "</w:hyperlink>")
    from test_docx_visible_controls import blocked

    blocked('<w:p><w:hyperlink w:anchor="bookmark">' + nested + "</w:hyperlink></w:p>")


def test_control_markup_in_foreign_word_namespace_is_not_accepted_by_local_name():
    from test_docx_visible_controls import blocked

    foreign = (
        '<x:sdt xmlns:x="http://purl.oclc.org/ooxml/wordprocessingml/main"><x:sdtContent/></x:sdt>'
    )
    blocked("<w:p>" + foreign + "</w:p>")


def test_hidden_control_result_still_requires_known_non_placeholder_content():
    from test_docx_visible_controls import blocked

    hidden = "<w:r><w:rPr><w:vanish/></w:rPr>" + literal("Prompt") + "</w:r>"
    blocked("<w:p>" + control(hidden, "<w:showingPlcHdr/>") + "</w:p>")


def test_reading_control_does_not_change_original_package_bytes():
    from hashlib import sha256

    raw = fixture(
        control(p(literal("Main") + ref())), foot=note(content=control(p(literal("Note"))))
    )[0]
    original = sha256(raw).hexdigest()
    s = build(raw)
    requests = tuple(
        api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text) for f in s.fragments
    )
    assert len(api().map_control_spans(raw, s, requests=requests)) == len(requests)
    assert s.complete and sha256(raw).hexdigest() == original == s.source_sha256
