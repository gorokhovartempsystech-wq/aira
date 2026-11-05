"""The plain extension cannot relax source, shape, raw or output boundaries."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

from test_docx_compatibility_catalog import alternate, choice
from test_docx_compatibility_contexts import fixture
from test_docx_visible_main import canonical, payload
from test_docx_visible_plain_controls import api, build, error, plain, request, run

from ara.docx_analysis.visible_main import VisibleLimits


def test_mapping_rebuilds_one_coherent_view_per_batch_including_empty(monkeypatch):
    api()
    module = import_module("ara.docx_analysis.compatibility_contexts._read")
    original, calls = module.build_compatibility_view, []

    def counted(*a, **kw):
        calls.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(module, "build_compatibility_view", counted)
    raw = fixture("<w:p>" + plain(run("A") + run("B")) + "</w:p>")[0]
    s = build(raw)
    assert s.complete and calls == [1]
    for requests in ((request(s.fragments[0]),) * 50, ()):
        calls.clear()
        result = api().map_plain_control_spans(raw, s, requests=requests)
        assert len(result) == len(requests) and calls == [1]


def test_raw_unselected_plain_control_bounds_still_precede_dom(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw control bounds")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    body = alternate(choice("x", plain("<w:p/>")) + choice("w", plain("<w:p/>")))
    raw = fixture(body)[0]
    error("view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_pieces=1)))


def test_exact_identity_input_and_snapshot_shapes_are_enforced():
    raw = fixture("<w:p>" + plain(run()) + "</w:p>")[0]
    for kw in (dict(document_id="bad"), dict(storage_revision=True), dict(limits=object())):
        error("invalid_input", lambda kw=kw: build(raw, **kw))
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))
    s = build(raw)
    error("invalid_snapshot", lambda: api().map_plain_control_spans(raw, object(), requests=()))
    error(
        "invalid_snapshot",
        lambda: api().map_plain_control_spans(
            raw, replace(s, fragments=list(s.fragments)), requests=()
        ),
    )
    q = request(s.fragments[0])
    error("invalid_input", lambda: api().map_plain_control_spans(raw, s, requests=[q]))
    error(
        "invalid_span",
        lambda: api().map_plain_control_spans(raw, s, requests=(replace(q, quote="Fake"),)),
    )


def test_uniformity_evidence_and_control_coverage_fit_the_same_exact_manifest_bound():
    raw = fixture(plain("<w:p>" + run("Text") + "</w:p>") * 20)[0]
    s = build(raw)
    maximum = len(canonical(payload(s)))
    assert build(raw, limits=VisibleLimits(max_manifest_bytes=maximum)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_manifest_bytes=maximum - 1)),
    )
    assert build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage))) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage) - 1)),
    )


def test_bound_and_unknown_types_remain_atomic_gates_even_with_valid_plain_payload():
    for props in ('<w:dataBinding w:xpath="/x" w:storeItemID="synthetic"/>', "<w:date/>"):
        s = build(fixture("<w:p>" + plain(run("Private"), props=props) + "</w:p>")[0])
        assert not s.complete and s.analysis_text == "" and s.fragments == ()
        assert "Private" not in repr(s)


def test_fresh_process_has_no_application_io_or_xml_serialization():
    raw = fixture("<w:p>" + plain(run("Fixture")) + "</w:p>")[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from uuid import UUID
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected I/O or XML serialization")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.visible_plain_controls import (
 build_plain_control_snapshot,map_plain_control_spans,VisibleSpanRequest)
s=build_plain_control_snapshot(data,document_id=UUID(int=1),storage_revision=1,
 source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Fixture"
f=s.fragments[0]
m=map_plain_control_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,7,"Fixture"),))
assert len(m)==1 and len(m[0].slices)==1
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


def test_rich_control_fields_and_note_references_keep_prior_behavior():
    from test_docx_note_catalog import note
    from test_docx_visible_controls import control
    from test_docx_visible_fields import simple
    from test_docx_visible_notes import p, ref

    body = "<w:p>" + control(simple() + "<w:r>" + ref() + "</w:r>") + "</w:p>"
    raw = fixture(body, foot=note("2", content=p("<w:t>Foot</w:t>")))[0]
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Cached", "Foot"]
    assert len(s.references) == 1
    assert api().map_plain_control_spans(raw, s, requests=tuple(request(f) for f in s.fragments))


def test_nested_rich_inline_and_cell_wrappers_preserve_plain_roles():
    from test_docx_table_catalog import cell, paragraph, row, table
    from test_docx_visible_controls import control

    bodies = (
        "<w:p>" + control(plain(run("Text"))) + "</w:p>",
        table(row(control(plain(cell(paragraph("Text"))))), 1),
    )
    for body in bodies:
        s = build(fixture(body)[0])
        assert s.complete and s.analysis_text == "Text"


def test_empty_plain_row_is_rejected_even_when_other_rows_prove_the_grid():
    from test_docx_table_catalog import cell, paragraph, row, table

    body = table(plain("") + row(cell(paragraph("Would be partial"))), 1)
    s = build(fixture(body)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    assert any(c.code == "unsupported_plain_control_context" for c in s.coverage)


def test_invalid_deleted_cell_cannot_skip_payload_without_table_proof():
    from test_docx_table_catalog import cell, paragraph, row, table

    body = table(
        row(
            plain(cell("<w:p><w:unknown/></w:p>", "<w:cellDel/>"))
            + cell(paragraph("Would be partial"))
        ),
        1,
    )
    s = build(fixture(body)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()


def test_nonidentical_current_formatting_is_not_silently_normalized():
    body = "<w:p>" + plain(run("A", "<w:b/>") + run("B", '<w:b w:val="true"/>')) + "</w:p>"
    s = build(fixture(body)[0])
    assert not s.complete and s.analysis_text == ""
    assert any(c.code == "unsupported_plain_control_formatting" for c in s.coverage)


def test_plain_generated_markers_and_closed_field_results_are_explicitly_unsupported():
    from test_docx_visible_fields import simple

    s = build(fixture("<w:p>" + plain(simple()) + "</w:p>")[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    assert any(c.code == "unsupported_plain_control_content" for c in s.coverage)
