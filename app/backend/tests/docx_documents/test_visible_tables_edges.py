"""Bounds, catalog reuse, unsupported branches and no-I/O table mapping."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_table_catalog import cell, paragraph, row, source, table
from test_docx_visible_main import canonical, codes, payload, rehash
from test_docx_visible_tables import api, build, error, request


def test_batch_builds_each_catalog_once(monkeypatch):
    tables = import_module("ara.docx_analysis.tables")
    moves = import_module("ara.docx_analysis.moves")
    shared = import_module("ara.docx_analysis.visible_main._build")
    raw, _ = source(table(row(cell(paragraph("ABC"))), 1))
    s = build(raw)
    calls = []
    for module, name in (
        (tables, "read_table_catalog"),
        (moves, "read_move_catalog"),
        (shared, "read_style_context"),
    ):
        original = getattr(module, name)

        def spy(*args, original=original, name=name, **kwargs):
            calls.append(name)
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, spy)
    results = api().map_table_spans(raw, s, requests=(request(s.fragments[0]),) * 100)
    assert len(results) == 100 and all(x == results[0] for x in results)
    assert sorted(calls) == ["read_move_catalog", "read_style_context", "read_table_catalog"]


@pytest.mark.parametrize("what", ["aggregate", "namespace", "table_nesting"])
def test_limits_precede_semantic_dom(monkeypatch, what):
    parser = import_module("ara.docx_package.projection._parse")

    def forbidden(*args, **kwargs):
        raise AssertionError("Table view DOM precedes preflight bounds")

    monkeypatch.setattr(parser, "_BoundedBuilder", forbidden)
    kwargs = {}
    body = table(row(cell(paragraph("A"))), 1)
    if what == "aggregate":
        kwargs["limits"] = api().VisibleLimits(max_xml_nodes=2)
    elif what == "namespace":
        body = body.replace("<w:tbl>", '<w:tbl xmlns:huge="' + "x" * 4096 + '">')
        kwargs["limits"] = api().VisibleLimits(max_xml_characters=1024)
    else:
        for _ in range(16):
            body = table(row(cell(body)), 1)
    error("view_limit_exceeded", lambda: build(source(body)[0], **kwargs))


def test_text_request_and_manifest_bounds_apply_to_full_snapshot():
    raw, _ = source(table(row(cell(paragraph("ABC")) + cell(paragraph("DEF")))))
    s = build(raw)
    for limits in (
        api().VisibleLimits(max_paragraphs=1),
        api().VisibleLimits(max_runs=1),
        api().VisibleLimits(max_text_characters=7),
        api().VisibleLimits(max_coverage_items=1),
    ):
        error("view_limit_exceeded", lambda limits=limits: build(raw, limits=limits))
    size = len(canonical(payload(s)))
    assert build(raw, limits=api().VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=size - 1)),
    )
    q = request(s.fragments[0])
    for limits in (
        api().VisibleLimits(max_span_requests=1),
        api().VisibleLimits(max_requested_characters=5),
        api().VisibleLimits(max_mapped_slices=1),
    ):
        error(
            "view_limit_exceeded",
            lambda limits=limits: api().map_table_spans(raw, s, requests=(q, q), limits=limits),
        )
    error(
        "view_limit_exceeded",
        lambda: api().map_table_spans(raw, s, requests=(), limits=api().VisibleLimits(max_runs=1)),
    )


def test_foreign_dto_shapes_and_rehashed_addresses_are_not_trusted():
    raw, _ = source(table(row(cell(paragraph("ABC")) + cell(paragraph("DEF")))))
    s = build(raw)

    class Trap:
        def __eq__(self, other):
            raise AssertionError("foreign equality")

        def __repr__(self):
            raise AssertionError("foreign repr")

        def __iter__(self):
            raise AssertionError("foreign iteration")

    for fake in (
        replace(s, fragments=Trap()),
        replace(s, analysis_text=Trap()),
        replace(s, profile=Trap()),
        replace(s, complete=1),
    ):
        error("invalid_snapshot", lambda fake=fake: api().map_table_spans(raw, fake, requests=()))
    a, b = s.fragments
    fake = rehash(
        replace(
            s, fragments=(replace(a, pieces=(replace(a.pieces[0], anchor=b.pieces[0].anchor),)), b)
        )
    )
    error("invalid_snapshot", lambda: api().map_table_spans(raw, fake, requests=()))
    error("invalid_input", lambda: build(raw, storage_revision=True))
    error("invalid_input", lambda: build(raw, limits={}))
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))


def test_mapping_rejects_wrong_quote_and_whole_batch_atomically():
    raw, _ = source(table(row(cell(paragraph("ABC"))), 1))
    s = build(raw)
    q = request(s.fragments[0])
    error(
        "invalid_span", lambda: api().map_table_spans(raw, s, requests=(q, replace(q, quote="BAD")))
    )
    error(
        "unknown_fragment",
        lambda: api().map_table_spans(raw, s, requests=(replace(q, fragment_id="missing"),)),
    )
    error("invalid_input", lambda: api().map_table_spans(raw, s, requests=[q]))


@pytest.mark.parametrize(
    "props",
    [
        "<w:tcBorders><w:unknown/></w:tcBorders>",
        "<w:tcMar><w:top/><w:top/></w:tcMar>",
        '<w:noWrap w:val="maybe"/>',
        '<w:hideMark w:extra="x"/>',
        "<w:shd>visible unaccounted text</w:shd>",
        "<w:shd/><w:shd/>",
    ],
)
def test_unknown_or_malformed_cell_metadata_not_ignored(props):
    s = build(source(table(row(cell(paragraph("A"), props)), 1))[0])
    assert not s.complete and s.fragments == ()
    assert ("blocked", "unsupported_table_properties") in codes(s)


def test_empty_cells_and_canonical_continuation_still_authenticate_source():
    rows = row(cell("<w:p/>", '<w:vMerge w:val="restart"/>'))
    rows += row(cell('<w:p w:rsidR="012345ab"/>', "<w:vMerge/>"))
    raw, _ = source(table(rows, 1))
    s = build(raw)
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert api().map_table_spans(raw, s, requests=()) == ()
    other, _ = source(table(row(cell(paragraph("Different"))), 1))
    error("source_mismatch", lambda: api().map_table_spans(other, s, requests=()))


def test_fresh_process_build_and_map_without_application_io():
    raw, _ = source(table(row(cell(paragraph("ABC")) + cell(paragraph("DEF")))))
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
from ara.docx_analysis.visible_tables import build_table_snapshot,map_table_span
s=build_table_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
f=s.fragments[1]
m=map_table_span(data,s,fragment_id=f.fragment_id,start=0,end=3,quote="DEF")
assert s.complete and s.analysis_text=="ABC\\n\\nDEF" and m.slices[0].anchor.path==(0,0,1,1,0,0,0)
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_cell_paragraph_boundaries_and_unrecognized_empty_continuation_are_blocked():
    text = "<w:p><w:pPr><w:rPr><w:vanish/></w:rPr></w:pPr><w:r><w:t>A</w:t></w:r></w:p>"
    s = build(source(table(row(cell(text)), 1))[0])
    assert not s.complete and s.fragments == ()
    assert ("blocked", "unresolved_paragraph_boundary") in codes(s)
    rows = row(cell("<w:p/>", '<w:vMerge w:val="restart"/>'))
    rows += row(cell('<w:p s:unknown="1"/>', "<w:vMerge/>"))
    s = build(source(table(rows, 1))[0])
    assert not s.complete and s.analysis_text == ""
    assert ("blocked", "unresolved_merged_cell_content") in codes(s)


def test_default_table_style_does_not_block_a_document_without_tables():
    from test_docx_visible_main import source as styled_source
    from test_docx_visible_main import style

    raw, _ = styled_source(paragraph("Plain"), style("T", kind="table", attrs='w:default="1"'))
    s = build(raw)
    assert s.complete and s.analysis_text == "Plain"
    assert s.fragments[0].flow_anchor == s.fragments[0].story_anchor
