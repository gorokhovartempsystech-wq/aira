"""Raster accounting cannot weaken package, source, raw or output bounds."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_compatibility_catalog import alternate, choice
from test_docx_compatibility_contexts import fixture
from test_docx_visible_inline_images import api, build, chunk, drawing, error, png, request, source
from test_docx_visible_main import canonical, payload
from test_docx_visible_notes import p

from ara.docx_analysis.visible_main import VisibleLimits


def test_batch_rebuilds_one_selected_view_including_empty(monkeypatch):
    api()
    module = import_module("ara.docx_analysis.compatibility_contexts._read")
    original = module.build_compatibility_view
    calls = []

    def counted(*a, **kw):
        calls.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(module, "build_compatibility_view", counted)
    raw = source()[0]
    s = build(raw)
    assert s.complete and calls == [1]
    for requests in ((request(s.fragments[0]),) * 50, ()):
        calls.clear()
        assert len(api().map_inline_image_spans(raw, s, requests=requests)) == len(requests)
        assert calls == [1]


def test_raw_drawing_limits_cover_discarded_content_before_first_dom(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw drawing bounds")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    body = alternate(choice("x", p(drawing() + drawing())) + choice("w", "<w:p/>"))
    raw = fixture(body)[0]
    error("view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_pieces=1)))


def test_binary_chunk_budget_covers_unreferenced_images_before_first_dom(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raster chunk bounds")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    raw = source("<w:p/>")[0]
    error("view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_pieces=2)))


def test_exact_manifest_coverage_and_text_bounds_include_image_evidence():
    raw = source()[0]
    s = build(raw)
    size = len(canonical(payload(s)))
    assert build(raw, limits=VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_manifest_bytes=size - 1))
    )
    assert build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage))) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage) - 1)),
    )
    assert build(raw, limits=VisibleLimits(max_text_characters=len(s.analysis_text))) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_text_characters=len(s.analysis_text) - 1)),
    )


def test_identity_input_shapes_and_changed_source_are_rejected():
    raw = source()[0]
    for kw in (dict(document_id="bad"), dict(storage_revision=True), dict(limits=object())):
        error("invalid_input", lambda kw=kw: build(raw, **kw))
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))
    s = build(raw)
    error(
        "invalid_snapshot",
        lambda: api().map_inline_image_spans(raw, replace(s, references=[]), requests=()),
    )
    error("invalid_input", lambda: api().map_inline_image_spans(raw, s, requests=[]))
    error(
        "invalid_span",
        lambda: api().map_inline_image_spans(
            raw, s, requests=(replace(request(s.fragments[0]), quote="fake"),)
        ),
    )


@pytest.mark.parametrize(
    "binary",
    [
        png()[:40] + bytes([png()[40] ^ 1]) + png()[41:],
        png()[:-12] + chunk(b"ABCD", b"") + png()[-12:],
        png()[:33] + chunk(b"acTL", b"\x00" * 8) + png()[33:],
        png()[:-12] + chunk(b"IDAT", b"") + png()[-12:] + b"junk",
    ],
)
def test_crc_unknown_critical_animation_and_trailing_binary_are_not_accepted(binary):
    s = build(source(binary=binary)[0])
    assert not s.complete and s.analysis_text == ""


def test_fresh_process_has_no_network_application_io_pixel_codec_or_xml_serialization():
    raw = source()[0]
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
from ara.docx_analysis.visible_inline_images import (
 build_inline_image_snapshot,map_inline_image_spans,VisibleSpanRequest)
s=build_inline_image_snapshot(data,document_id=UUID(int=1),storage_revision=1,
 source_sha256=sha256(data).hexdigest())
assert s.complete and len(s.fragments)==2
f=s.fragments[0]
q=VisibleSpanRequest(f.fragment_id,0,len(f.text),f.text)
assert map_inline_image_spans(data,s,requests=(q,))
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


def test_field_code_images_are_not_visible_boundaries_but_cached_result_images_are():
    from test_docx_visible_fields import char, instr, simple

    content = char("begin") + instr("SYNTHETIC") + drawing() + char("separate")
    content += "<w:t>Left</w:t>" + drawing() + "<w:t>Right</w:t>" + char("end")
    s = build(source(p(content))[0])
    assert s.complete and [f.text for f in s.fragments] == ["Left", "Right"]
    assert len([c for c in s.coverage if c.code == "inline_raster_boundary"]) == 1
    simple_body = (
        "<w:p>" + simple(content="<w:r><w:t>A</w:t>" + drawing() + "<w:t>B</w:t></w:r>") + "</w:p>"
    )
    s = build(source(simple_body)[0])
    assert s.complete and s.analysis_text == "A\n\nB"


def test_discarded_drawing_payload_does_not_become_active_but_unknown_active_content_blocks():
    body = alternate(
        choice("w", p("<w:t>Kept</w:t>")) + choice("x", p(drawing(props='title="Private"')))
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Kept"
    assert any(c.code == "unreferenced_raster_image" and c.status == "excluded" for c in s.coverage)
    bad = build(source(p(drawing()) + "<w:p><w:unknown/></w:p>")[0])
    assert not bad.complete and bad.fragments == ()
    assert not any(c.code == "unreferenced_raster_image" for c in bad.coverage)


def test_raster_chunk_budget_is_aggregate_across_parts():
    raw = source(
        "<w:p/>", extras={"custom/second.bin": png()}, types={"custom/second.bin": "image/png"}
    )[0]
    error("view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_pieces=5)))
    s = build(raw, limits=VisibleLimits(max_pieces=6))
    assert s.complete and len([c for c in s.coverage if c.code == "unreferenced_raster_image"]) == 2


def test_jpeg_metadata_bytes_are_not_visible_requirements():
    from test_docx_visible_inline_images import JPEG_BASELINE

    text = b"Private metadata <text>not a requirement</text>"
    segment = b"\xff\xfe" + (len(text) + 2).to_bytes(2, "big") + text
    raw = source(binary=JPEG_BASELINE[:2] + segment + JPEG_BASELINE[2:], mime="image/jpeg")[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Before😀\n\nAfterЯ"
    assert "Private" not in repr(s) + s.analysis_text


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.replace(b"\xff\xc0\x00\x11", b"\xff\xc1\x00\x11", 1),
        lambda raw: raw.replace(b"\xff\xc0\x00\x11", b"\xff\xc0\x00\x01", 1),
        lambda raw: raw.replace(b"\xff\xda\x00\x0c", b"\xff\xda\xff\xff", 1),
        lambda raw: raw[:-2] + b"\xff\x00",
    ],
)
def test_unsupported_jpeg_frame_and_malformed_marker_framing_are_atomic(change):
    from test_docx_visible_inline_images import JPEG_BASELINE

    s = build(source(binary=change(JPEG_BASELINE), mime="image/jpeg")[0])
    assert not s.complete and s.analysis_text == ""


def test_supported_crop_transform_and_locks_are_metadata_in_both_namespace_families():
    for strict, crop in ((False, "1500"), (True, "1.5%")):
        d = drawing(strict=strict, inline_attrs='distL="0" distR="1"')
        d = d.replace(
            "<pic:cNvPicPr/>",
            '<pic:cNvPicPr preferRelativeResize="true"><a:picLocks noCrop="1"/></pic:cNvPicPr>',
        )
        d = d.replace("<a:stretch>", f'<a:srcRect l="{crop}"/><a:stretch>')
        d = d.replace("<a:xfrm>", '<a:xfrm rot="60000" flipH="true">')
        d = d.replace("<wp:docPr", '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr')
        s = build(source(p("<w:t>A</w:t>" + d + "<w:t>B</w:t>"), strict=strict)[0])
        assert s.complete and s.analysis_text == "A\n\nB"
