"""Whole-source limits and shared proofs cover all original story parts."""

import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_section_catalog import BASE, reference, section
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_main import canonical, payload
from test_docx_visible_stories import api, build, error, fixture, story_xml, table_style


def test_exact_global_text_manifest_and_piece_limits():
    raw = fixture()[0]
    s = build(raw)
    assert s.complete and len(s.analysis_text) == 20
    exact = api().VisibleLimits(
        max_text_characters=20, max_pieces=3, max_manifest_bytes=len(canonical(payload(s)))
    )
    assert build(raw, limits=exact) == s
    for caps in (
        dict(max_text_characters=19),
        dict(max_pieces=2),
        dict(max_manifest_bytes=len(canonical(payload(s))) - 1),
        dict(max_coverage_items=1),
    ):
        error(
            "view_limit_exceeded", lambda caps=caps: build(raw, limits=api().VisibleLimits(**caps))
        )


def test_all_stories_including_orphan_count_before_any_semantic_dom(monkeypatch):
    parsing = import_module("ara.docx_analysis.visible_stories._parse")
    sections = import_module("ara.docx_analysis.sections._xml")

    def forbidden(*a, **kw):
        raise AssertionError("Semantic DOM before whole-source budget")

    monkeypatch.setattr(parsing, "build_tree", forbidden)
    monkeypatch.setattr(sections, "build_tree", forbidden)
    raw = fixture(
        extras={"custom/Unused.xml": story_xml(paragraph("Orphan"))},
        types={"custom/Unused.xml": BASE + "header+xml"},
    )[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_paragraphs=3)))
    raw = fixture()[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_runs=2)))


def test_table_structural_budget_is_shared_across_story_parts_before_dom(monkeypatch):
    parsing = import_module("ara.docx_analysis.visible_stories._parse")
    sections = import_module("ara.docx_analysis.sections._xml")

    def forbidden(*a, **kw):
        raise AssertionError("Semantic DOM before aggregate table cap")

    monkeypatch.setattr(parsing, "build_tree", forbidden)
    monkeypatch.setattr(sections, "build_tree", forbidden)
    tables = table(row(cell(paragraph("Cell"))), 1) * 400
    raw = fixture(
        tables + section(reference() + reference("F", "footer")), header=tables, footer=tables
    )[0]
    error("view_limit_exceeded", lambda: build(raw))


def test_multiple_styled_story_tables_use_one_shared_source_style_proof(monkeypatch):
    proof = import_module("ara.docx_analysis.table_styles._read")
    original = proof.catalog
    calls = []

    def counted(*args, **kw):
        calls.append(1)
        return original(*args, **kw)

    monkeypatch.setattr(proof, "catalog", counted)
    content = table(row(cell(paragraph("Cell"))), 1, '<w:tblStyle w:val="T"/>')
    raw = fixture(
        content + section(reference() + reference("F", "footer")),
        header=content,
        footer=content,
        styles=table_style("T"),
    )[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Cell\n\nCell\n\nCell" and calls == [1]


def test_main_section_properties_history_never_activates_fake_old_table():
    from test_docx_section_catalog import previous

    body = paragraph("Body") + section(reference(), history=previous(payload=table()))
    raw = fixture(body)[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Body\n\nHeader"
    assert not any(e.code == "table_structure" for e in s.coverage)


@pytest.mark.parametrize(
    "prop",
    [
        '<w:cols w:space="720"><w:col w:w="3000"/><w:col w:w="3000"/></w:cols>',
        '<w:pgBorders><w:top w:val="single"/></w:pgBorders>',
        '<w:footnotePr><w:pos w:val="beneathText"/><w:numFmt w:val="decimal"/></w:footnotePr>',
    ],
)
def test_known_nontext_section_property_containers_do_not_hide_unknown_text(prop):
    body = paragraph("Body") + section(reference(), prop)
    assert build(fixture(body)[0]).complete
    closing = prop.rfind("</w:")
    bad = prop[:closing] + paragraph("Must block") + prop[closing:]
    s = build(fixture(paragraph("Body") + section(reference(), bad))[0])
    assert not s.complete and s.fragments == () and s.analysis_text == ""


def test_fresh_process_does_not_read_app_settings_files_network_or_models():
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
from ara.docx_analysis.visible_stories import (
    build_story_snapshot,map_story_spans,VisibleSpanRequest,
)
s=build_story_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Body\\n\\nFooter\\n\\nHeader"
f=s.fragments[-1]
m=map_story_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,6,"Header"),))
assert len(m)==1 and m[0].slices[0].anchor.part_name=="custom/H.xml"
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


def test_old_main_paragraph_properties_cannot_activate_tables_or_header_references():
    from test_docx_section_catalog import previous

    old = previous("pPr", table() + section(reference("MISSING")))
    body = "<w:p><w:pPr>" + old + "</w:pPr><w:r><w:t>Body</w:t></w:r></w:p>"
    raw = fixture(body + section(reference()))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Body\n\nHeader"
    assert any(e.code == "historical_properties" for e in s.coverage)
    assert not any(e.code == "table_structure" for e in s.coverage)


@pytest.mark.parametrize(
    "header",
    [
        table(row(cell(paragraph("Hidden row")), "<w:hidden/>"), 1),
        table(
            row(cell(paragraph("Origin"), '<w:vMerge w:val="restart"/>'))
            + row(cell(paragraph("Nonempty continuation"), "<w:vMerge/>")),
            1,
        ),
    ],
)
def test_header_table_visibility_and_continuation_guards_stay_atomic(header):
    s = build(fixture(header=header)[0])
    assert not s.complete and s.fragments == s.paragraphs == s.runs == ()
    assert s.analysis_text == "" and not any(e.status == "included" for e in s.coverage)


def test_character_style_visibility_is_shared_across_stories_without_hiding_main():
    from test_docx_visible_main import style

    styles = style("Secret", "<w:rPr><w:vanish/></w:rPr>", kind="character")
    header = (
        "<w:p><w:r><w:t>A</w:t></w:r>"
        '<w:r><w:rPr><w:rStyle w:val="Secret"/></w:rPr><w:t>SECRET</w:t></w:r>'
        "<w:r><w:t>B</w:t></w:r></w:p>"
    )
    raw = fixture(header=header, styles=styles)[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Body\n\nFooter\n\nAB"
    hidden = [e for e in s.coverage if e.code == "hidden_run"]
    assert len(hidden) == 1 and hidden[0].anchor.part_name == "custom/H.xml"


def test_comments_remain_original_bytes_and_do_not_become_story_requirements():
    from hashlib import sha256

    from test_docx_visible_main import W

    comments = (
        f'<w:comments xmlns:w="{W}"><w:comment w:id="1">'
        + paragraph("COMMENT MUST NOT BE ANALYZED")
        + "</w:comment></w:comments>"
    ).encode()
    raw = fixture(
        extras={"custom/Comments.xml": comments},
        types={"custom/Comments.xml": BASE + "comments+xml"},
    )[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Body\n\nFooter\n\nHeader"
    assert any(
        e.code == "comments_policy" and e.part_name == "custom/Comments.xml" for e in s.coverage
    )
    assert sha256(raw).hexdigest() == s.source_sha256
