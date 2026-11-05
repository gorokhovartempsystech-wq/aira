"""No source spoofing, unsafe unused assertion or resource escape at unlisted admission."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_table_catalog import cell, row, table
from test_docx_visible_floating_images import anchor
from test_docx_visible_inline_images import IMAGE, png
from test_docx_visible_main import SR, R, canonical, codes, payload
from test_docx_visible_plain_controls import run
from test_docx_visible_unlisted import (
    DEFS,
    MIME,
    PART,
    api,
    build,
    error,
    original,
    selected,
    source,
)

from ara.docx_analysis.visible_main import VisibleLimits


def test_one_fresh_selected_context_per_mapping_batch_even_empty(monkeypatch):
    api()
    mod = import_module("ara.docx_analysis.compatibility_contexts._read")
    old, calls = mod.build_compatibility_view, []

    def counted(*a, **kw):
        calls.append(1)
        return old(*a, **kw)

    monkeypatch.setattr(mod, "build_compatibility_view", counted)
    raw, _ = source()
    s = build(raw)
    assert s.complete and calls == [1]
    f = s.fragments[0]
    request = api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)
    for requests in ((request,) * 30, ()):
        calls.clear()
        assert len(api().map_unlisted_spans(raw, s, requests=requests)) == len(requests)
        assert calls == [1]


def test_combined_raw_numbering_bounds_precede_every_semantic_dom(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw combined bounds")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.visible_unlisted._numbering"), "build_tree", forbidden
    )
    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    raw, _ = source(
        definitions=DEFS.replace(
            '<w:lvlText w:val="%1."/>', '<w:lvlText w:val="' + "X" * 1000 + '"/>'
        )
    )
    error("view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_xml_characters=500)))


def test_output_coverage_manifest_limits_and_identity_are_exact():
    raw, _ = source()
    s = build(raw)
    for kw in (dict(document_id="bad"), dict(storage_revision=True), dict(limits=object())):
        error("invalid_input", lambda kw=kw: build(raw, **kw))
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))
    error(
        "invalid_snapshot",
        lambda: api().map_unlisted_spans(raw, replace(s, references=[]), requests=()),
    )
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


@pytest.mark.parametrize(
    "links",
    [
        [{"Id": "N", "Type": SR + "numbering", "Target": "Numbers.xml"}],
        [
            {
                "Id": "N",
                "Type": R + "numbering",
                "Target": "https://example.invalid/numbering.xml",
                "TargetMode": "External",
            }
        ],
        [
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "Other", "Type": R + "numbering", "Target": "Numbers.xml"},
        ],
    ],
)
def test_wrong_family_external_and_ambiguous_numbering_links_never_become_metadata(links):
    s = build(source(links=links)[0])
    assert not s.complete and s.analysis_text == ""
    assert ("excluded", "unused_numbering_definition") not in codes(s)


def test_wrong_owner_outgoing_links_and_multiple_parts_remain_gated():
    raw, parts = source()
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="N" Type="{R}numbering" Target="Numbers.xml"/></Relationships>'
    ).encode()
    variants = [
        dict(extra_parts={"custom/_rels/Numbers.xml.rels": rels}),
        dict(extra_parts={"custom/Other.xml": parts[PART]}, extra_types={"custom/Other.xml": MIME}),
    ]
    for kw in variants:
        s = build(source(**kw)[0])
        assert not s.complete and s.fragments == ()
        assert ("excluded", "unused_numbering_definition") not in codes(s)


def test_table_and_floating_image_share_the_new_style_context_and_original_paths():
    body = table(
        row(
            cell(
                "<w:p><w:pPr><w:widowControl/></w:pPr>"
                + run(atoms="<w:t>Before</w:t>" + anchor())
                + run("After")
                + "</w:p>"
            )
        ),
        1,
    )
    raw, parts = source(
        selected(body),
        extra_parts={IMAGE: png()},
        extra_types={IMAGE: "image/png"},
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "I", "Type": R + "image", "Target": "picture.bin"},
        ],
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "BeforeAfter"
    assert ("metadata", "floating_raster_reference") in codes(s)
    original(raw, parts, s)


def test_inert_import_and_build_in_a_fresh_process():
    raw, _ = source()
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
from ara.docx_analysis.visible_unlisted import build_unlisted_snapshot,map_unlisted_spans
s=build_unlisted_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=='A😀Я'
assert map_unlisted_spans(data,s,requests=()) == ()
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


def test_early_compatibility_failure_has_the_new_style_profile():
    from test_docx_visible_unlisted import PROFILE, STYLE_PROFILE

    body = (
        '<w:p xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:x="urn:future" mc:MustUnderstand="x">' + run("Private") + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.profile == PROFILE and s.style_context.profile == STYLE_PROFILE
    assert not s.complete and s.style_context.status == "blocked"
    assert s.fragments == s.runs == s.paragraphs == s.references == () and s.analysis_text == ""


def test_namespace_alias_and_non_xml_whitespace_do_not_create_new_pagination_rules():
    for prop in (
        '<w:widowControl xmlns:x="urn:foreign" x:val="1"/>',
        "<w:widowControl>\u00a0</w:widowControl>",
    ):
        s = build(source("<w:p><w:pPr>" + prop + "</w:pPr>" + run("Private") + "</w:p>")[0])
        assert not s.complete and s.analysis_text == ""
    s = build(source("<w:p>" + run("Private", props="<w:widowControl/>") + "</w:p>")[0])
    assert not s.complete and s.fragments == ()


def test_orphan_numbering_relationship_without_a_numbering_part_is_not_ignored():
    from test_docx_visible_main import source as main_source

    raw, _ = main_source(
        "<w:p>" + run("Private") + "</w:p>",
        links=[
            {
                "Id": "N",
                "Type": R + "numbering",
                "Target": "https://example.invalid/n.xml",
                "TargetMode": "External",
            }
        ],
    )
    s = build(raw)
    assert not s.complete and s.analysis_text == "" and s.fragments == ()


def test_historical_numbering_does_not_activate_a_list_in_the_final_view():
    from test_docx_visible_unlisted import NUMPR

    body = (
        '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr>'
        + NUMPR
        + "</w:pPr></w:pPrChange></w:pPr>"
        + run("Kept")
        + "</w:p>"
    )
    raw, parts = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "Kept"
    assert ("excluded", "unused_numbering_definition") in codes(s)
    original(raw, parts, s)


def test_strict_numbering_never_admits_transitional_only_alignment_aliases():
    for property_xml in (
        '<w:lvlJc w:val="left"/>',
        '<w:pPr><w:tabs><w:tab w:val="right" w:pos="360"/></w:tabs></w:pPr>',
        '<w:pPr><w:ind w:left="360"/></w:pPr>',
    ):
        definitions = DEFS.replace("</w:lvl>", property_xml + "</w:lvl>")
        assert build(source(definitions=definitions)[0]).complete
        s = build(source(definitions=definitions, strict=True, encoding="utf-16")[0])
        assert not s.complete and s.analysis_text == ""
    definitions = DEFS.replace("</w:lvl>", '<w:lvlJc w:val="center"/></w:lvl>')
    assert build(source(definitions=definitions, strict=True)[0]).complete


def test_equivalent_decimal_ids_collide_and_long_numeric_text_is_bounded_before_conversion():
    variants = [
        DEFS.replace("</w:numbering>", "")
        + '<w:num w:numId="0001"><w:abstractNumId w:val="0"/></w:num>',
        DEFS.replace('w:numId="1"', 'w:numId="' + "9" * 5000 + '"'),
        DEFS.replace('<w:abstractNumId w:val="0"/>', '<w:abstractNumId w:val="+0000"/>')
        + '<w:abstractNum w:abstractNumId="0000"/>',
    ]
    for definitions in variants:
        s = build(source(definitions=definitions)[0])
        assert not s.complete and s.fragments == ()


def test_unknown_part_prevents_proven_numbering_exclusion():
    s = build(source(extra_parts={"custom/Other.xml": b"<Unknown/>"})[0])
    assert not s.complete and s.analysis_text == ""
    assert ("excluded", "unused_numbering_definition") not in codes(s)


def test_note_story_with_pagination_keeps_reference_mapping_and_own_source():
    from test_docx_note_catalog import note
    from test_docx_visible_main import W
    from test_docx_visible_notes import ref

    body = "<w:p>" + run(atoms="<w:t>Main</w:t>" + ref()) + "</w:p>"
    foot = (
        '<w:footnotes xmlns:w="'
        + W
        + '">'
        + note("2", content="<w:p><w:pPr><w:widowControl/></w:pPr>" + run("Note") + "</w:p>")
        + "</w:footnotes>"
    ).encode()
    raw, parts = source(
        body,
        extra_parts={"custom/Foot.xml": foot},
        extra_types={
            "custom/Foot.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            )
        },
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "Foot", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Main", "Note"]
    assert len(s.references) == 1
    original(raw, parts, s)
