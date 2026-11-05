"""History bounds before DOM, exact source identity and inert combined reading."""

import os
import subprocess
import sys
from dataclasses import fields
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_current_tables import (
    api,
    cell,
    error,
    fixture,
    history,
    payload,
    read,
    row,
    source,
    table,
)


def test_history_limit_exact_manifest_and_all_original_nodes():
    raw, xml = fixture()
    c = read(raw)
    nodes = len(list(ET.fromstring(xml).iter()))
    assert (
        read(
            raw,
            limits=api().CurrentTableLimits(
                max_histories=4, max_xml_nodes=nodes, max_manifest_bytes=len(payload(c))
            ),
        )
        == c
    )
    for values in (
        dict(max_histories=3),
        dict(max_xml_nodes=nodes - 1),
        dict(max_manifest_bytes=len(payload(c)) - 1),
    ):
        error(
            "table_limit_exceeded",
            lambda values=values: read(raw, limits=api().CurrentTableLimits(**values)),
        )


@pytest.mark.parametrize("variant", ["duplicate", "opaque", "namespace", "depth", "cells"])
def test_whole_input_caps_include_histories_before_any_semantic_dom(monkeypatch, variant):
    parser = import_module("ara.docx_package.projection._parse")

    def forbidden(*args, **kwargs):
        raise AssertionError("Current table DOM before whole-input budgets")

    monkeypatch.setattr(parser, "_BoundedBuilder", forbidden)
    if variant == "duplicate":
        props, caps = history("cell") * 2, dict(max_histories=1)
    elif variant == "opaque":
        props = history("cell", "<w:unknown>" + history("table") * 2 + "</w:unknown>")
        caps = dict(max_histories=2)
    elif variant == "namespace":
        props = history("cell", '<w:unknown xmlns:large="' + "x" * 4096 + '"/>')
        caps = dict(max_xml_characters=1024)
    elif variant == "depth":
        props = history("cell", "<w:unknown>" * 15 + "</w:unknown>" * 15)
        caps = dict(max_xml_depth=10)
    else:
        props = history("cell", "<w:unknown><w:tc/><w:tc/></w:unknown>")
        caps = dict(max_cells=1)
    raw = source(table(row(cell(properties=props)), 1))[0]
    error("table_limit_exceeded", lambda: read(raw, limits=api().CurrentTableLimits(**caps)))


def test_history_marker_under_fake_owner_does_not_authorize_context():
    raw = source("<w:p><w:tcPr>" + history("cell") + "</w:tcPr></w:p>")[0]
    c = read(raw)
    assert c.status == "blocked" and c.issues[0].code == "unsupported_table_context"
    assert c.tables == c.histories == ()


def test_foreign_word_history_and_foreign_previous_root_are_not_accepted():
    s = "http://purl.oclc.org/ooxml/wordprocessingml/main"
    marker = f'<z:tcPrChange xmlns:z="{s}" z:id="1"><z:tcPr/></z:tcPrChange>'
    c = read(source(table(row(cell(properties=marker)), 1))[0])
    assert c.status == "blocked" and c.issues[0].code == "unsupported_table_context"
    marker = f'<w:tcPrChange w:id="1"><z:tcPr xmlns:z="{s}"/></w:tcPrChange>'
    c = read(source(table(row(cell(properties=marker)), 1))[0])
    assert c.status == "blocked" and c.issues[0].code == "invalid_table_history"


def test_exact_inputs_mutated_limits_and_package_failures():
    raw = fixture()[0]
    for bad in (None, bytearray(raw), memoryview(raw), "not bytes"):
        error(
            "invalid_input",
            lambda bad=bad: api().read_current_table_catalog(
                bad, source_sha256=sha256(raw).hexdigest()
            ),
        )
    for bad in (None, "A" * 64, "0" * 63):
        error(
            "invalid_input",
            lambda bad=bad: api().read_current_table_catalog(raw, source_sha256=bad),
        )
    error("source_mismatch", lambda: api().read_current_table_catalog(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: read(raw, limits={}))
    old = import_module("ara.docx_analysis.tables")
    error("invalid_input", lambda: read(raw, limits=old.TableLimits()))
    for f in fields(api().CurrentTableLimits):
        for value in (True, 0, -1, 1.5, f.default + 1):
            error(
                "invalid_input",
                lambda f=f, value=value: api().CurrentTableLimits(**{f.name: value}),
            )
    for missing in (False, True):
        limit = api().CurrentTableLimits()
        if missing:
            object.__delattr__(limit, "max_histories")
        else:
            object.__setattr__(limit, "max_histories", True)
        error("invalid_input", lambda: read(raw, limits=limit))
    from ara.docx_package import DocxError

    for data in (b"not zip", b"x" * 33554433):
        with pytest.raises(DocxError):
            read(data)


def test_archive_size_guard_precedes_hashing(monkeypatch):
    from ara.docx_package import DocxError

    module = import_module("ara.docx_analysis.current_tables._read")

    def forbidden(*args, **kwargs):
        raise AssertionError("Hash before archive size guard")

    monkeypatch.setattr(module, "sha256", forbidden)
    with pytest.raises(DocxError) as caught:
        api().read_current_table_catalog(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


def test_changed_history_with_identical_text_cannot_reuse_snapshot():
    from io import BytesIO
    from zipfile import ZipFile

    from docx_package_fixtures import build_package
    from test_docx_visible_current_tables import api as visible_api
    from test_docx_visible_current_tables import build, definitions
    from test_docx_visible_current_tables import error as visible_error

    raw, xml = fixture(styles=definitions())
    s = build(raw)
    with ZipFile(BytesIO(raw)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["custom/Main.xml"] = xml.replace(b'w:id="41"', b'w:id="99"')
    changed = build_package(parts)
    assert changed != raw and build(changed).analysis_text == s.analysis_text
    visible_error(
        "source_mismatch", lambda: visible_api().map_current_table_spans(changed, s, requests=())
    )
    visible_error(
        "view_limit_exceeded",
        lambda: build(raw, limits=visible_api().VisibleLimits(max_manifest_bytes=1)),
    )


def test_fresh_process_catalog_snapshot_mapping_do_not_access_application_io():
    from test_docx_visible_current_tables import definitions

    raw = fixture(styles=definitions())[0]
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
from ara.docx_analysis.current_tables import read_current_table_catalog
from ara.docx_analysis.visible_current_tables import (
    build_current_table_snapshot,map_current_table_spans,VisibleSpanRequest,
)
c=read_current_table_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="indexed" and len(c.histories)==4
s=build_current_table_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Before\\n\\nA\\n\\nB\\n\\nAfter"
f=s.fragments[1]
m=map_current_table_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,1,"A"),))
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


def test_nested_current_tables_keep_distinct_flows_and_exclude_only_proven_histories():
    from test_docx_current_tables import paragraph
    from test_docx_move_catalog import resolve
    from test_docx_visible_current_tables import api as visible_api
    from test_docx_visible_current_tables import build, request

    nested = table(row(cell(paragraph("Nested"))), 1, history("table", "<w:tbl/>"))
    outer = table(
        row(cell(paragraph("Outer") + nested + paragraph("Tail"), history("cell"))),
        1,
        history("table", "<w:unknown><w:tbl><w:tr><w:tc/></w:tr></w:tbl></w:unknown>"),
    )
    raw, xml = source(outer)
    c = read(raw)
    assert c.status == "indexed" and len(c.tables) == 2 and len(c.histories) == 3
    s = build(raw)
    assert s.complete and s.analysis_text == "Outer\n\nNested\n\nTail"
    assert [f.flow_anchor.path for f in s.fragments] == [
        (0, 0, 2, 0),
        (0, 0, 2, 0, 2, 2, 0),
        (0, 0, 2, 0),
    ]
    events = [e for e in s.coverage if e.code.startswith("historical_table_")]
    assert len(events) == 3 and all(e.status == "excluded" for e in events)
    assert {e.anchor for e in events} == {h.anchor for h in c.histories}
    result = visible_api().map_current_table_spans(
        raw, s, requests=tuple(request(f) for f in s.fragments)
    )
    root = ET.fromstring(xml)
    assert [resolve(root, m.slices[0].anchor).text for m in result] == ["Outer", "Nested", "Tail"]


def test_history_events_count_towards_visible_coverage_budget():
    from test_docx_visible_current_tables import api as visible_api
    from test_docx_visible_current_tables import build
    from test_docx_visible_current_tables import error as visible_error

    raw = source(table(row(cell(properties=history("cell"))), 1, history("table")))[0]
    visible_error(
        "view_limit_exceeded",
        lambda: build(raw, limits=visible_api().VisibleLimits(max_coverage_items=1)),
    )


def test_history_attributes_are_metadata_only_and_have_no_repr_payload():
    attrs = 'w:id="-00000001" w:author="PRIVATE_AUTHOR" w:date="2026-11-04T00:00:00Z"'
    raw = source(table(properties=history("table", attrs=attrs)))[0]
    c = read(raw)
    assert c.status == "indexed" and len(c.histories) == 1
    serialized = payload(c)
    for value in (b"PRIVATE_AUTHOR", b"-00000001", b"2026-11-04"):
        assert value not in serialized and value.decode() not in repr(c.histories[0])
