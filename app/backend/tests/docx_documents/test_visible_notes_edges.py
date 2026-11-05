"""Aggregate source bounds, atomic unknown coverage, exact manifests and no I/O."""

import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_note_catalog import note
from test_docx_section_catalog import BASE
from test_docx_table_catalog import paragraph
from test_docx_visible_main import canonical, codes, payload
from test_docx_visible_notes import api, build, error, fixture, literal, note_xml, p, ref


def test_whole_original_notes_including_orphans_and_special_content_count_before_any_dom(
    monkeypatch,
):
    def forbidden(*a, **kw):
        raise AssertionError("DOM before aggregate raw input limits")

    for module in (
        "ara.docx_analysis.visible_notes._parse",
        "ara.docx_analysis.sections._xml",
        "ara.docx_analysis.notes._xml",
    ):
        monkeypatch.setattr(import_module(module), "build_tree", forbidden)
    raw, xml, parts = fixture()
    count = sum(len(list(ET.fromstring(v).iter())) for v in [xml, *parts.values()])
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_xml_nodes=count - 1)),
    )
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_paragraphs=2)))
    raw = fixture(
        foot=note("2")
        + note("0", "separator", content='<w:unknown xmlns:huge="' + "x" * 2048 + '"/>')
    )[0]
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_xml_characters=1024)),
    )


def test_exact_manifest_output_text_and_fragment_caps():
    raw = fixture()[0]
    s = build(raw)
    size = len(canonical(payload(s)))
    assert build(raw, limits=api().VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=size - 1)),
    )
    error(
        "view_limit_exceeded",
        lambda: build(
            raw, limits=api().VisibleLimits(max_text_characters=len(s.analysis_text) - 1)
        ),
    )
    raw = fixture(p(literal("A") + ref() + literal("B") + ref() + literal("C")))[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_paragraphs=3)))


def test_unrelated_unknown_part_prevents_orphan_exclusion_and_all_output():
    raw = fixture(
        extras={"custom/Other.xml": b"<other/>"}, types={"custom/Other.xml": "application/xml"}
    )[0]
    s = build(raw)
    assert (
        not s.complete
        and s.fragments == s.references == s.paragraphs == s.runs == ()
        and s.analysis_text == ""
    )
    assert ("blocked", "unread_part") in codes(s)
    assert not ({("excluded", "unreferenced_note"), ("excluded", "special_note")} & codes(s))


def test_unbound_same_id_does_not_resolve_the_linked_parts_missing_target():
    extra = {"custom/Spare.xml": note_xml(note("2"))}
    raw = fixture(foot=note("3"), extras=extra, types={"custom/Spare.xml": BASE + "footnotes+xml"})[
        0
    ]
    s = build(raw)
    assert not s.complete and s.fragments == s.references == ()
    assert ("blocked", "unresolved_note_reference") in codes(s)


@pytest.mark.parametrize("attrs", [' w:other="x"', ' w:customMarkFollows="maybe"'])
def test_hidden_reference_does_not_bypass_closed_marker_syntax(attrs):
    body = "<w:p><w:r><w:rPr><w:vanish/></w:rPr>" + ref(attrs=attrs) + "</w:r></w:p>"
    s = build(fixture(body)[0])
    assert not s.complete and s.fragments == s.references == ()


def test_all_boundaries_are_linear_and_never_emit_generated_source_pieces():
    body = p(ref() * 300 + literal("A") + ref() * 300 + literal("B"))
    s = build(fixture(body)[0])
    assert s.complete and s.analysis_text == "A\n\nB\n\nFoot 🧪" and len(s.references) == 600
    a, b = s.fragments[:2]
    assert all(
        r.before_fragment_id is None and r.after_fragment_id == a.fragment_id
        for r in s.references[:300]
    )
    assert all(
        r.before_fragment_id == a.fragment_id and r.after_fragment_id == b.fragment_id
        for r in s.references[300:]
    )
    assert all(piece.end > piece.start for f in s.fragments for piece in f.pieces)


def test_note_namespace_must_agree_with_actual_main_namespace():
    raw = fixture(extras={"custom/Foot.xml": note_xml(note(), strict=True)})[0]
    s = build(raw)
    assert not s.complete and s.fragments == s.references == () and s.analysis_text == ""


def test_style_context_and_table_proof_are_shared_across_multiple_notes(monkeypatch):
    from test_docx_table_catalog import cell, row, table
    from test_docx_visible_styled_tables import table_style

    body = p(ref() + ref("3"))
    content = table(row(cell(paragraph("Cell"))), 1, '<w:tblStyle w:val="T"/>')
    raw = fixture(
        body, foot=note("2", content=content) + note("3", content=content), styles=table_style("T")
    )[0]
    proof = import_module("ara.docx_analysis.visible_styled_tables._reader")
    count = 0
    original = proof.build_proof

    def wrapped(*a, **kw):
        nonlocal count
        count += 1
        return original(*a, **kw)

    monkeypatch.setattr(proof, "build_proof", wrapped)
    s = build(raw)
    assert s.complete and s.analysis_text == "Cell\n\nCell" and count == 1


def test_fresh_process_source_read_and_batch_map_have_no_application_io():
    raw = fixture()[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
from uuid import UUID
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.visible_notes import build_note_snapshot,map_note_spans,VisibleSpanRequest
s=build_note_snapshot(data,document_id=UUID("12345678-1234-4234-8234-123456789abc"),storage_revision=1,
                     source_sha256=sha256(data).hexdigest())
assert s.complete and len(s.references)==1 and len(s.fragments)==3
f=s.fragments[-1]
m=map_note_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,len(f.text),f.text),))
assert m[0].slices[0].anchor.part_name=="custom/Foot.xml"
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


def test_exact_input_and_archive_size_are_checked_before_hash_or_source_parse(monkeypatch):
    from hashlib import sha256

    from test_docx_visible_main import DOC

    from ara.docx_package import DocxError

    raw = fixture()[0]
    for invalid in (None, bytearray(raw), "bad"):
        error(
            "invalid_input",
            lambda invalid=invalid: api().build_note_snapshot(
                invalid, document_id=DOC, storage_revision=1, source_sha256=sha256(raw).hexdigest()
            ),
        )
    error("invalid_input", lambda: build(raw, limits={}))
    caps = api().VisibleLimits()
    object.__setattr__(caps, "max_pieces", True)
    error("invalid_input", lambda: build(raw, limits=caps))

    def forbidden(*a, **kw):
        raise AssertionError("Hash before archive limit")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.visible_notes._build"), "sha256", forbidden
    )
    with pytest.raises(DocxError) as caught:
        api().build_note_snapshot(
            b"x" * 33554433, document_id=DOC, storage_revision=1, source_sha256="0" * 64
        )
    assert caught.value.code == "package_limit_exceeded"


def test_reference_in_deleted_cell_does_not_activate_a_missing_note():
    from test_docx_retained_tables import marker
    from test_docx_table_catalog import cell, row, table

    removed = cell(p(ref("999")), marker("cellDel"))
    retained = cell(p(literal("Cell") + ref()))
    raw = fixture(table(row(removed + retained), 1))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Cell\n\nFoot 🧪"
    assert len(s.references) == 1 and ("excluded", "deleted_table_cell") in codes(s)


def test_hidden_generated_self_label_does_not_split_visible_note_text():
    content = "<w:p><w:r><w:t>A</w:t></w:r>"
    content += "<w:r><w:rPr><w:vanish/></w:rPr><w:footnoteRef/></w:r>"
    content += "<w:r><w:t>B</w:t></w:r></w:p>"
    s = build(fixture(p(ref()), foot=note(content=content))[0])
    assert s.complete and s.analysis_text == "AB" and len(s.fragments) == 1
    assert len(s.references) == 1 and ("metadata", "note_number_marker") not in codes(s)
    assert len(s.fragments[0].pieces) == 2


@pytest.mark.parametrize("identity,name", [("+00", "different"), ("8", "same")])
def test_range_id_alias_or_name_alone_cannot_disambiguate_moves_in_unused_note(identity, name):
    from test_docx_move_catalog import group, run

    first = "<w:p>" + group(name="same", content=run("Old"))
    first += group("To", name="same", content=run("Kept")) + "</w:p>"
    second = "<w:p>" + group(identity=identity, name=name) + "</w:p>"
    raw = fixture(p(ref()), foot=note("2", content=first) + note("3", content=second))[0]
    s = build(raw)
    assert not s.complete and s.fragments == s.references == ()
    assert ("blocked", "move_catalog_blocked") in codes(s)


def test_malformed_note_link_rejected_before_source_rebuild(monkeypatch):
    from dataclasses import replace

    raw = fixture()[0]
    s = build(raw)
    bad = replace(s.references[0], before_fragment_id=True)
    s = replace(s, references=(bad,))

    def forbidden(*a, **kw):
        raise AssertionError("Unbounded foreign record reached source rebuild")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.visible_notes._api"), "build_note_snapshot", forbidden
    )
    error("invalid_snapshot", lambda: api().map_note_spans(raw, s, requests=()))
