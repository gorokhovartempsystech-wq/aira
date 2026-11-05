"""Logical column derivation stays bounded, inert and source-addressed."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_grid_tables import api, cell, error, fixture, gridless, payload, read, row, source


def test_exact_column_xml_and_manifest_limits_and_immutable_records():
    raw, xml = fixture()
    c = read(raw)
    nodes = len(list(ET.fromstring(xml).iter()))
    assert (
        read(
            raw,
            limits=api().GridTableLimits(
                max_grid_columns=2, max_xml_nodes=nodes, max_manifest_bytes=len(payload(c))
            ),
        )
        == c
    )
    for caps in (
        dict(max_grid_columns=1),
        dict(max_xml_nodes=nodes - 1),
        dict(max_manifest_bytes=len(payload(c)) - 1),
    ):
        error(
            "table_limit_exceeded",
            lambda caps=caps: read(raw, limits=api().GridTableLimits(**caps)),
        )
    with pytest.raises(FrozenInstanceError):
        c.tables[0].column_count = 999
    assert not hasattr(c.tables[0], "__dict__")
    for f in fields(api().GridTableLimits):
        for value in (True, 0, -1, 1.5, f.default + 1):
            error(
                "invalid_input", lambda f=f, value=value: api().GridTableLimits(**{f.name: value})
            )
    limits = api().GridTableLimits()
    object.__delattr__(limits, "max_revisions")
    error("invalid_input", lambda: read(raw, limits=limits))


def test_all_original_xml_is_counted_before_dom(monkeypatch):
    from test_docx_current_tables import history

    parser = import_module("ara.docx_package.projection._parse")

    def forbidden(*a, **kw):
        raise AssertionError("Semantic DOM before original XML caps")

    monkeypatch.setattr(parser, "_BoundedBuilder", forbidden)
    props = history("cell", '<w:unknown xmlns:large="' + "x" * 4096 + '"/>')
    raw = source(gridless(row(cell(properties=props))))[0]
    error(
        "table_limit_exceeded",
        lambda: read(raw, limits=api().GridTableLimits(max_xml_characters=1024)),
    )


def test_span_overflow_never_allocates_generated_column_nodes():
    for span in ("1025", "99999999999999999999"):
        raw = source(gridless(row(cell(properties='<w:gridSpan w:val="' + span + '"/>'))))[0]
        error("table_limit_exceeded", lambda: read(raw))


def test_size_cap_precedes_hashing_and_invalid_input_is_fixed(monkeypatch):
    from hashlib import sha256

    from ara.docx_package import DocxError

    raw = fixture()[0]
    for bad in (None, bytearray(raw), "bad"):
        error(
            "invalid_input",
            lambda bad=bad: api().read_grid_table_catalog(
                bad, source_sha256=sha256(raw).hexdigest()
            ),
        )
    error("source_mismatch", lambda: api().read_grid_table_catalog(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: read(raw, limits={}))

    def forbidden(*a, **kw):
        raise AssertionError("Hash before archive size cap")

    monkeypatch.setattr(import_module("ara.docx_analysis.grid_tables._read"), "sha256", forbidden)
    with pytest.raises(DocxError) as caught:
        api().read_grid_table_catalog(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


def test_derived_grid_event_obeys_visible_coverage_budget():
    from test_docx_visible_grid_tables import api as visible_api
    from test_docx_visible_grid_tables import build
    from test_docx_visible_grid_tables import error as visible_error

    raw = fixture()[0]
    visible_error(
        "view_limit_exceeded",
        lambda: build(raw, limits=visible_api().VisibleLimits(max_coverage_items=1)),
    )


def test_fresh_process_does_not_access_application_io():
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
from ara.docx_analysis.grid_tables import read_grid_table_catalog
from ara.docx_analysis.visible_grid_tables import (
    build_grid_table_snapshot,map_grid_table_spans,VisibleSpanRequest,
)
c=read_grid_table_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="indexed" and c.tables[0].column_count==2
assert c.tables[0].grid_anchor is None and c.tables[0].grid_columns==()
s=build_grid_table_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="A\\n\\nB\\n\\nC\\n\\nD"
f=s.fragments[1]
m=map_grid_table_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,1,"B"),))
assert len(m)==1 and len(m[0].slices)==1
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


def test_derived_grid_combines_current_history_revisions_and_neutral_style_without_rewrite():
    from hashlib import sha256

    from test_docx_current_tables import history, paragraph, table
    from test_docx_move_catalog import resolve
    from test_docx_retained_tables import marker
    from test_docx_visible_grid_tables import api as visible_api
    from test_docx_visible_grid_tables import build, request
    from test_docx_visible_main import codes
    from test_docx_visible_styled_tables import table_style

    removed = cell(paragraph("OLD"), marker("cellDel") + '<w:gridSpan w:val="99"/>')
    kept = cell(paragraph("New 🧪"), marker("cellIns") + history("cell"))
    body = table(row(removed + kept, marker("ins")), 0, '<w:tblStyle w:val="Good"/>')
    body = body.replace("</w:tblGrid>", history("grid", "<w:gridCol/>" * 5) + "</w:tblGrid>", 1)
    raw, xml = source(body, table_style("Good"))
    s = build(raw)
    assert s.complete and s.analysis_text == "New 🧪"
    assert {
        ("metadata", "derived_table_grid"),
        ("metadata", "table_style_proven"),
        ("excluded", "deleted_table_cell"),
        ("excluded", "historical_table_grid"),
        ("excluded", "historical_table_properties"),
    } <= codes(s)
    (mapped,) = visible_api().map_grid_table_spans(raw, s, requests=(request(s.fragments[0]),))
    assert mapped.slices[0].anchor.path == (0, 0, 2, 2, 1, 0, 0)
    assert resolve(ET.fromstring(xml), mapped.slices[0].anchor).text == "New 🧪"
    assert sha256(raw).hexdigest() == s.source_sha256


def test_nested_missing_and_explicit_grids_keep_actual_independent_flows():
    from test_docx_current_tables import paragraph, table
    from test_docx_visible_grid_tables import build

    nested = table(row(cell(paragraph("Nested"))), 1)
    raw = source(gridless(row(cell(paragraph("Outer") + nested + paragraph("Tail")))))[0]
    c = read(raw)
    assert [t.grid_mode for t in c.tables] == ["inferred", "explicit"]
    s = build(raw)
    assert s.complete and s.analysis_text == "Outer\n\nNested\n\nTail"
    assert [f.flow_anchor.path for f in s.fragments] == [
        (0, 0, 0, 0),
        (0, 0, 0, 0, 1, 1, 0),
        (0, 0, 0, 0),
    ]
    derived = [e for e in s.coverage if e.code == "derived_table_grid"]
    assert len(derived) == 1 and derived[0].anchor.path == (0, 0)
