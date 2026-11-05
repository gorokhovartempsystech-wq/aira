"""Deleted payload remains source-bound and budgeted even when not analyzed."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_retained_tables import (
    api,
    cell,
    error,
    fixture,
    marker,
    payload,
    read,
    row,
    source,
    table,
)


def test_exact_budgets_include_historical_and_deleted_revision_markers():
    raw, xml = fixture()
    c = read(raw)
    nodes = len(list(ET.fromstring(xml).iter()))
    assert (
        read(
            raw,
            limits=api().RetainedTableLimits(
                max_xml_nodes=nodes, max_revisions=4, max_manifest_bytes=len(payload(c))
            ),
        )
        == c
    )
    for caps in (
        dict(max_revisions=3),
        dict(max_xml_nodes=nodes - 1),
        dict(max_manifest_bytes=len(payload(c)) - 1),
    ):
        error(
            "table_limit_exceeded",
            lambda caps=caps: read(raw, limits=api().RetainedTableLimits(**caps)),
        )
    with pytest.raises(FrozenInstanceError):
        c.revisions[0].kind = "other"
    assert not hasattr(c.revisions[0], "__dict__")


@pytest.mark.parametrize("kind", ["revisions", "characters", "depth", "cells"])
def test_deleted_whole_payload_limits_precede_dom(monkeypatch, kind):
    parser = import_module("ara.docx_package.projection._parse")

    def forbidden(*a, **kw):
        raise AssertionError("DOM allocated before deleted payload cap")

    monkeypatch.setattr(parser, "_BoundedBuilder", forbidden)
    if kind == "revisions":
        body, caps = (
            "<w:p><w:unknown>" + marker("ins") * 3 + "</w:unknown></w:p>",
            dict(max_revisions=3),
        )
    elif kind == "characters":
        body, caps = '<w:p xmlns:large="' + "x" * 4096 + '"/>', dict(max_xml_characters=1024)
    elif kind == "depth":
        body, caps = (
            "<w:p>" + "<w:unknown>" * 12 + "</w:unknown>" * 12 + "</w:p>",
            dict(max_xml_depth=10),
        )
    else:
        body, caps = "<w:p><w:unknown><w:tc/><w:tc/></w:unknown></w:p>", dict(max_cells=2)
    raw = source(table(row(cell(body, marker("cellDel")) + cell()), 1))[0]
    error("table_limit_exceeded", lambda: read(raw, limits=api().RetainedTableLimits(**caps)))


def test_exact_inputs_mutated_limits_and_original_size_before_hash(monkeypatch):
    raw = fixture()[0]
    for bad in (None, bytearray(raw), memoryview(raw), "bad"):
        error(
            "invalid_input",
            lambda bad=bad: api().read_retained_table_catalog(
                bad, source_sha256=sha256(raw).hexdigest()
            ),
        )
    for bad in (None, "A" * 64, "0" * 63):
        error(
            "invalid_input",
            lambda bad=bad: api().read_retained_table_catalog(raw, source_sha256=bad),
        )
    error("source_mismatch", lambda: api().read_retained_table_catalog(raw, source_sha256="0" * 64))
    error(
        "invalid_input",
        lambda: read(
            raw, limits=import_module("ara.docx_analysis.current_tables").CurrentTableLimits()
        ),
    )
    for f in fields(api().RetainedTableLimits):
        for value in (True, 0, -1, 1.5, f.default + 1):
            error(
                "invalid_input",
                lambda f=f, value=value: api().RetainedTableLimits(**{f.name: value}),
            )
    for missing in (False, True):
        limits = api().RetainedTableLimits()
        if missing:
            object.__delattr__(limits, "max_revisions")
        else:
            object.__setattr__(limits, "max_revisions", True)
        error("invalid_input", lambda: read(raw, limits=limits))
    from ara.docx_package import DocxError

    def forbidden(*a, **kw):
        raise AssertionError("Hash before size cap")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.retained_tables._read"), "sha256", forbidden
    )
    with pytest.raises(DocxError) as caught:
        api().read_retained_table_catalog(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


def test_deleted_nested_table_style_is_not_used_by_retained_text():
    from test_docx_retained_tables import paragraph
    from test_docx_visible_retained_tables import build
    from test_docx_visible_styled_tables import table_style

    old = table(row(cell(paragraph("OLD"))), 1, '<w:tblStyle w:val="Bad"/>')
    body = table(
        row(cell(old, marker("cellDel")) + cell(paragraph("New"))), 1, '<w:tblStyle w:val="Good"/>'
    )
    raw = source(body, table_style("Good") + table_style("Bad", "<w:rPr><w:vanish/></w:rPr>"))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "New"
    assert len([c for c in s.coverage if c.code == "table_style_proven"]) == 1


def test_whole_main_move_guard_is_not_bypassed_inside_deleted_cell():
    from test_docx_visible_main import codes
    from test_docx_visible_retained_tables import build

    old = '<w:p><w:moveTo w:id="1"><w:r><w:t>OLD</w:t></w:r></w:moveTo></w:p>'
    raw = source(table(row(cell(old, marker("cellDel")) + cell()), 1))[0]
    s = build(raw)
    assert not s.complete and s.fragments == () and ("blocked", "move_catalog_blocked") in codes(s)


def test_fresh_process_has_no_application_io():
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
from ara.docx_analysis.retained_tables import read_retained_table_catalog
from ara.docx_analysis.visible_retained_tables import (
    build_retained_table_snapshot,map_retained_table_spans,VisibleSpanRequest,
)
c=read_retained_table_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="indexed" and len(c.revisions)==3
s=build_retained_table_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Before\\n\\nA\\n\\nB\\n\\nC\\n\\nD\\n\\nAfter"
f=s.fragments[2]
m=map_retained_table_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,1,"B"),))
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


def test_retained_vertical_origin_survives_deleted_physical_siblings():
    from test_docx_retained_tables import paragraph
    from test_docx_visible_retained_tables import api as visible_api
    from test_docx_visible_retained_tables import build, request

    removed = cell(paragraph("OLD"), marker("cellDel") + '<w:gridSpan w:val="wrong"/>')
    rows = row(
        removed
        + cell(paragraph("Origin"), '<w:vMerge w:val="restart"/>')
        + cell(paragraph("Right"))
    )
    rows += row(cell("<w:p/>", "<w:vMerge/>") + removed + cell(paragraph("Below")))
    raw = source(table(rows, 2))[0]
    c = read(raw)
    assert c.status == "indexed" and len(c.revisions) == 2
    origin = c.tables[0].rows[0].cells[0]
    continuation = c.tables[0].rows[1].cells[0]
    assert origin.anchor.path == (0, 0, 1, 1)
    assert continuation.merge_origin == origin.anchor and continuation.column_start == 0
    s = build(raw)
    assert s.complete and s.analysis_text == "Origin\n\nRight\n\nBelow"
    assert (
        len(visible_api().map_retained_table_spans(raw, s, requests=(request(s.fragments[0]),)))
        == 1
    )


def test_duplicate_row_insert_and_conflicting_row_markers_are_atomic():
    for markers in (marker("ins") * 2, marker("ins") + marker("del")):
        c = read(source(table() + table(row(properties=markers)))[0])
        assert c.status == "blocked" and c.tables == c.histories == c.revisions == ()
        assert c.issues[0].code == "invalid_table_revision"


def test_deleted_cell_envelope_never_authorizes_nonwhitespace_or_wrong_direct_blocks():
    bad_cells = (
        "<w:tc>TEXT<w:tcPr>" + marker("cellDel") + "</w:tcPr><w:p/></w:tc>",
        "<w:tc><w:tcPr>" + marker("cellDel") + "</w:tcPr><w:unknown/></w:tc>",
        "<w:tc><w:p/><w:tcPr>" + marker("cellDel") + "</w:tcPr></w:tc>",
        "<w:tc><w:tcPr>" + marker("cellDel") + "</w:tcPr></w:tc>",
    )
    for bad in bad_cells:
        c = read(source(table(row(bad + cell()), 1))[0])
        assert c.status == "blocked" and c.revisions == ()
        assert c.issues[0].code == "invalid_table_revision"


def test_excluded_cells_and_insertion_metadata_obey_visible_coverage_budget():
    from test_docx_visible_retained_tables import api as visible_api
    from test_docx_visible_retained_tables import build
    from test_docx_visible_retained_tables import error as visible_error

    raw = fixture()[0]
    visible_error(
        "view_limit_exceeded",
        lambda: build(raw, limits=visible_api().VisibleLimits(max_coverage_items=1)),
    )
