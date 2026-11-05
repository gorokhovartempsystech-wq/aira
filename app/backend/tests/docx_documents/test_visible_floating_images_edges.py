"""Floating metadata must preserve source, profile and bounded mapping authority."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

from test_docx_compatibility_catalog import alternate, choice
from test_docx_compatibility_contexts import fixture
from test_docx_note_catalog import note
from test_docx_section_catalog import reference, section
from test_docx_visible_fields import char, instr
from test_docx_visible_floating_images import anchor, api, build, error, original, request
from test_docx_visible_inline_images import source
from test_docx_visible_main import R, canonical, payload
from test_docx_visible_notes import p, ref

from ara.docx_analysis.visible_main import VisibleLimits


def test_one_fresh_view_per_mapping_batch_and_empty_batch(monkeypatch):
    api()
    module = import_module("ara.docx_analysis.compatibility_contexts._read")
    original_view, calls = module.build_compatibility_view, []

    def counted(*a, **kw):
        calls.append(1)
        return original_view(*a, **kw)

    monkeypatch.setattr(module, "build_compatibility_view", counted)
    raw = source(p("<w:t>A</w:t>" + anchor() + "<w:t>B</w:t>"))[0]
    s = build(raw)
    assert s.complete and calls == [1]
    for requests in ((request(s.fragments[0]),) * 50, ()):
        calls.clear()
        assert len(api().map_floating_image_spans(raw, s, requests=requests)) == len(requests)
        assert calls == [1]


def test_raw_limits_cover_discarded_polygons_before_first_dom(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw polygon bounds")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    raw = fixture(alternate(choice("x", p(anchor(wrap="tight"))) + choice("w", "<w:p/>")))[0]
    error("view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_xml_nodes=5)))


def test_source_identity_shapes_and_exact_output_bounds():
    raw = source(p("<w:t>A</w:t>" + anchor() + "<w:t>B</w:t>"))[0]
    for kw in (dict(document_id="bad"), dict(storage_revision=True), dict(limits=object())):
        error("invalid_input", lambda kw=kw: build(raw, **kw))
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))
    s = build(raw)
    error(
        "invalid_snapshot",
        lambda: api().map_floating_image_spans(raw, replace(s, fragments=[]), requests=()),
    )
    error("invalid_input", lambda: api().map_floating_image_spans(raw, s, requests=[]))
    error(
        "invalid_span",
        lambda: api().map_floating_image_spans(
            raw, s, requests=(replace(request(s.fragments[0]), quote="fake"),)
        ),
    )
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


def test_floating_header_note_ownership_and_note_links_keep_original_sources():
    rels = (
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="I" Type="{R}image" Target="picture.bin"/></Relationships>'
    ).encode()
    links = [
        {"Id": "H", "Type": R + "header", "Target": "H.xml"},
        {"Id": "Foot", "Type": R + "footnotes", "Target": "Foot.xml"},
    ]
    raw, parts = source(
        p("<w:t>Main</w:t>" + ref()) + section(reference("H")),
        header=p("<w:t>H1</w:t>" + anchor() + "<w:t>H2</w:t>"),
        foot=note("2", content=p("<w:t>N1</w:t>" + anchor() + "<w:t>N2</w:t>")),
        extras={"custom/_rels/H.xml.rels": rels, "custom/_rels/Foot.xml.rels": rels},
        links=links,
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Main", "H1H2", "N1N2"]
    assert (
        len(s.references) == 1 and s.references[0].before_fragment_id == s.fragments[0].fragment_id
    )
    original(raw, parts, s)


def test_closed_field_code_and_result_do_not_gain_anchor_characters():
    content = char("begin") + instr("PRIVATE") + anchor() + char("separate")
    content += "<w:t>A</w:t>" + anchor() + "<w:t>B</w:t>" + char("end")
    raw, parts = source(p(content))
    s = build(raw)
    assert s.complete and s.analysis_text == "AB"
    original(raw, parts, s)


def test_all_required_positions_remain_validated_when_simple_position_is_selected():
    obj = anchor().replace('simplePos="0"', 'simplePos="true"')
    s = build(source(p("<w:t>A</w:t>" + obj + "<w:t>B</w:t>"))[0])
    assert s.complete and s.analysis_text == "AB"
    invalid = obj.replace('relativeFrom="column"', 'relativeFrom="unknown"')
    assert not build(source(p(invalid))[0]).complete


def test_fresh_process_has_no_application_io_or_serialization():
    raw = source(p("<w:t>A</w:t>" + anchor() + "<w:t>B</w:t>"))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from uuid import UUID
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError('Unexpected I/O or serialization')
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.visible_floating_images import (
 build_floating_image_snapshot,map_floating_image_spans,VisibleSpanRequest)
s=build_floating_image_snapshot(data,document_id=UUID(int=1),storage_revision=1,
 source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=='AB'
f=s.fragments[0]
q=VisibleSpanRequest(f.fragment_id,0,2,'AB')
assert len(map_floating_image_spans(data,s,requests=(q,))[0].slices)==2
blocked={'psycopg','sqlalchemy','onnxruntime','numpy','aira_ml','fastapi','PIL'}
assert not any(n.split('.')[0] in blocked for n in sys.modules)
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


def test_hidden_anchor_does_not_bypass_foreground_overlay_gate():
    raw = source(p(anchor(behind=False, attrs='hidden="true"')))[0]
    s = build(raw)
    assert not s.complete and s.analysis_text == ""
    assert any(c.code == "unsupported_floating_overlay" for c in s.coverage)


def test_optional_simple_position_flag_and_wrap_effects_preserve_logical_text():
    for wrap in ("square", "top"):
        d = anchor(wrap=wrap).replace('simplePos="0" ', "")
        name = "wrapSquare" if wrap == "square" else "wrapTopAndBottom"
        old = (
            '<wp:wrapSquare wrapText="bothSides"/>'
            if wrap == "square"
            else "<wp:wrapTopAndBottom/>"
        )
        attrs = 'wrapText="largest" ' if wrap == "square" else ""
        d = d.replace(
            old,
            f'<wp:{name} {attrs}distT="10" distB="20">'
            '<wp:effectExtent l="0" t="0" r="1" b="2"/>' + f"</wp:{name}>",
        )
        raw, parts = source(p("<w:t>A</w:t>" + d + "<w:t>B</w:t>"))
        s = build(raw)
        assert s.complete and s.analysis_text == "AB"
        original(raw, parts, s)


def test_wrong_namespace_or_non_xml_whitespace_in_position_metadata_is_not_silently_removed():
    d = anchor()
    variants = (
        d.replace("<wp:align>", "<wp:unknown>")
        .replace("</wp:align>", "</wp:unknown>")
        .replace("<wp:posOffset>0</wp:posOffset>", "<w:posOffset>0</w:posOffset>", 1),
        d.replace("<wp:wrapNone/>", "<wp:wrapNone/>\u00a0"),
        d.replace(
            '<wp:positionH relativeFrom="column">', '<wp:positionH relativeFrom="column">\u00a0'
        ),
    )
    for variant in variants:
        s = build(source(p(variant))[0])
        assert not s.complete and s.fragments == ()


def test_early_compatibility_failure_keeps_the_new_profile_and_no_output():

    raw = source(p(anchor()), attrs='mc:MustUnderstand="x"')[0]
    s = build(raw)
    assert s.profile == "docx-analysis/final-visible-floating-images-v1"
    assert not s.complete and s.fragments == s.references == s.runs == s.paragraphs == ()
    assert s.analysis_text == "" and s.style_context.status == "blocked"
    assert any(c.code == "compatibility_context_blocked" for c in s.coverage)
