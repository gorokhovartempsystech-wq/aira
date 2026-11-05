"""Inline raster objects preserve text boundaries and exact original source slices."""

import struct
import zlib
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_compatibility_contexts import fixture
from test_docx_move_catalog import resolve
from test_docx_note_catalog import note
from test_docx_section_catalog import reference, section
from test_docx_table_catalog import cell, row, table
from test_docx_visible_compatibility import selected
from test_docx_visible_controls import control
from test_docx_visible_main import DOC, SR, R, canonical, codes, payload, rehash
from test_docx_visible_notes import p, ref
from test_docx_visible_plain_controls import plain, run

PROFILE = "docx-analysis/final-visible-inline-images-v1"
IMAGE = "custom/picture.bin"


def api():
    return import_module("ara.docx_analysis.visible_inline_images")


def build(raw, **kw):
    return api().build_inline_image_snapshot(
        raw,
        **(dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()) | kw),
    )


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png():
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30"))
        + chunk(b"IEND", b"")
    )


# Synthetic 2x2 RGB fixtures, generated once with Pillow; no runtime dependency.
JPEG_BASELINE = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b"
    "0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e3334"
    "32ffdb0043010909090c0b0c180d0d1832211c21323232323232323232323232323232323232323232323232"
    "3232323232323232323232323232323232323232323232323232ffc000110800020002030122000211010311"
    "01ffc4001500010100000000000000000000000000000006ffc4001410010000000000000000000000000000"
    "0000ffc40014010100000000000000000000000000000006ffc4001411010000000000000000000000000000"
    "0000ffda000c03010002110311003f008b00bc5dffd9"
)
JPEG_PROGRESSIVE = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b"
    "0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e3334"
    "32ffdb0043010909090c0b0c180d0d1832211c21323232323232323232323232323232323232323232323232"
    "3232323232323232323232323232323232323232323232323232ffc200110800020002030122000211010311"
    "01ffc4001500010100000000000000000000000000000005ffc4001401010000000000000000000000000000"
    "0005ffda000c030100021003100000018a172fffc40014100100000000000000000000000000000000ffda00"
    "080101000105027fffc40014110100000000000000000000000000000000ffda0008010301013f017fffc400"
    "14110100000000000000000000000000000000ffda0008010201013f017fffc4001410010000000000000000"
    "0000000000000000ffda0008010100063f027fffc40014100100000000000000000000000000000000ffda00"
    "08010100013f217fffda000c030100020003000000100bffc400141101000000000000000000000000000000"
    "00ffda0008010301013f107fffc40014110100000000000000000000000000000000ffda0008010201013f10"
    "7fffc40014100100000000000000000000000000000000ffda0008010100013f107fffd9"
)


def drawing(*, strict=False, rid="I", props="", pic_props="", inline_attrs="", shape=""):
    base = (
        "http://purl.oclc.org/ooxml/drawingml/"
        if strict
        else "http://schemas.openxmlformats.org/drawingml/2006/"
    )
    return (
        f'<w:drawing xmlns:wp="{base}wordprocessingDrawing" xmlns:a="{base}main" '
        f'xmlns:pic="{base}picture"><wp:inline {inline_attrs}>'
        '<wp:extent cx="914400" cy="914400"/>'
        f'<wp:docPr id="1" name="Synthetic image" {props}/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        f'<a:graphic><a:graphicData uri="{base}picture"><pic:pic><pic:nvPicPr>'
        f'<pic:cNvPr id="0" name="Synthetic" {pic_props}/><pic:cNvPicPr/>'
        "</pic:nvPicPr><pic:blipFill>"
        f'<a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch>'
        "</pic:blipFill><pic:spPr>"
        '<a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{shape}'
        "</pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>"
    )


def source(
    body=None, *, strict=False, encoding="utf-8", binary=None, mime="image/png", links=None, **kw
):
    if body is None:
        body = p("<w:t>Before😀</w:t>" + drawing(strict=strict) + "<w:t>AfterЯ</w:t>")
    rels = [{"Id": "I", "Type": (SR if strict else R) + "image", "Target": "picture.bin"}]
    return fixture(
        body,
        strict=strict,
        encoding=encoding,
        extras={IMAGE: png() if binary is None else binary} | kw.pop("extras", {}),
        types={IMAGE: mime} | kw.pop("types", {}),
        links=rels if links is None else links,
        **kw,
    )


def request(f):
    return api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)


def original(raw, parts, s):
    result = api().map_inline_image_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    for f, m in zip(s.fragments, result, strict=True):
        text = []
        for item in m.slices:
            n = resolve(ET.fromstring(parts[item.anchor.part_name]), item.anchor)
            value = n.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            text.append(value[item.start : item.end])
        assert "".join(text) == f.text


def error(code, call):
    with pytest.raises(api().VisibleViewError) as e:
        call()
    assert e.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
@pytest.mark.parametrize(
    "binary,mime",
    [(png(), "image/png"), (JPEG_BASELINE, "image/jpeg"), (JPEG_PROGRESSIVE, "image/jpeg")],
)
def test_inline_png_jpeg_split_text_without_invented_characters(strict, encoding, binary, mime):
    raw, parts = source(strict=strict, encoding=encoding, binary=binary, mime=mime)
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.analysis_text == "Before😀\n\nAfterЯ"
    assert [f.text for f in s.fragments] == ["Before😀", "AfterЯ"]
    assert len({f.fragment_id for f in s.fragments}) == 2
    assert s.fragments[0].paragraph_anchor == s.fragments[1].paragraph_anchor
    assert ("metadata", "inline_raster_boundary") in codes(s)
    assert ("metadata", "raster_image_part") in codes(s)
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and s == build(raw)
    original(raw, parts, s)


@pytest.mark.parametrize("wrapper", ["selected", "rich", "cell"])
def test_inline_images_keep_logical_ownership_and_original_mc_addresses(wrapper):
    body = p("<w:t>One</w:t>" + selected(drawing()) + "<w:t>Two</w:t>")
    if wrapper == "selected":
        body = selected(body)
    elif wrapper == "rich":
        body = control(body)
    else:
        body = table(row(cell(body)), 1)
    raw, parts = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "One\n\nTwo"
    original(raw, parts, s)
    boundaries = [c for c in s.coverage if c.code == "inline_raster_boundary"]
    assert len(boundaries) == 1
    assert resolve(
        ET.fromstring(parts[boundaries[0].part_name]), boundaries[0].anchor
    ).tag.endswith("}drawing")
    if wrapper == "cell":
        f = s.fragments[0]
        assert resolve(ET.fromstring(parts[f.flow_anchor.part_name]), f.flow_anchor).tag.endswith(
            "}tc"
        )


@pytest.mark.parametrize("hidden", ["run", "doc", "picture"])
def test_hidden_images_do_not_split_visible_text_but_still_require_valid_structure(hidden):
    d = drawing(
        props='hidden="1"' if hidden == "doc" else "",
        pic_props='hidden="true"' if hidden == "picture" else "",
    )
    body = (
        "<w:p>"
        + run("Left")
        + run(props="<w:vanish/>" if hidden == "run" else "", atoms=d)
        + run("Right")
        + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "LeftRight" and len(s.fragments) == 1
    bad = body.replace("<pic:cNvPicPr/>", "<pic:cNvPicPr><a:unknown/></pic:cNvPicPr>")
    assert not build(source(bad)[0]).complete


def test_repeated_and_consecutive_images_are_read_once_as_parts_and_not_as_text():
    raw, parts = source(
        p(
            drawing()
            + drawing()
            + "<w:t>A</w:t>"
            + drawing()
            + drawing()
            + "<w:t>B</w:t>"
            + drawing()
        )
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "A\n\nB" and len(s.fragments) == 2
    assert len([c for c in s.coverage if c.code == "raster_image_part"]) == 1
    assert len([c for c in s.coverage if c.code == "inline_raster_boundary"]) == 5
    original(raw, parts, s)


def test_deleted_picture_does_not_revive_content_or_prevent_proven_orphan_exclusion():
    body = (
        '<w:p><w:del w:id="1">'
        + run(atoms=drawing().replace("pic:pic", "pic:unknown"))
        + "</w:del>"
        + run("Kept")
        + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Kept"
    assert ("excluded", "unreferenced_raster_image") in codes(s)


def test_empty_image_only_paragraph_has_no_fake_requirement():
    raw = source(p(drawing()))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert ("metadata", "inline_raster_boundary") in codes(s)
    assert api().map_inline_image_spans(raw, s, requests=()) == ()


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.replace("wp:inline", "wp:anchor"),
        lambda d: d.replace("pic:pic", "pic:chart"),
        lambda d: d.replace('<a:blip r:embed="I"/>', '<a:blip r:link="I"/>'),
        lambda d: d.replace('<a:blip r:embed="I"/>', '<a:blip r:embed="I"><a:extLst/></a:blip>'),
        lambda d: d.replace(
            "<pic:cNvPicPr/>", "<pic:cNvPicPr><w:txbxContent><w:p/></w:txbxContent></pic:cNvPicPr>"
        ),
        lambda d: d.replace(
            'name="Synthetic image"', 'name="Synthetic image" descr="Private alt text"'
        ),
        lambda d: d.replace('name="Synthetic"', 'name="Synthetic" title="Private title"'),
        lambda d: d.replace('cx="914400"', 'cx="-1"', 1),
        lambda d: d.replace("<a:avLst/>", '<a:avLst><a:gd name="x" fmla="val 1"/></a:avLst>'),
        lambda d: d.replace("<pic:spPr>", "<pic:spPr>UNREAD"),
        lambda d: d.replace("<a:graphic>", '<a:graphic bogus="1">'),
        lambda d: d.replace('<wp:docPr id="1"', '<wp:docPr id="-1"'),
        lambda d: d.replace("<a:stretch>", "<a:stretch><a:unknown/>"),
    ],
)
def test_unsupported_or_malformed_drawing_is_atomic_even_when_text_precedes_it(change):
    raw = source(p("<w:t>Private requirement</w:t>" + change(drawing())))[0]
    s = build(raw)
    assert (
        not s.complete
        and s.analysis_text == ""
        and s.fragments == s.runs == s.paragraphs == s.references == ()
    )
    assert "Private" not in repr(s)


@pytest.mark.parametrize(
    "links",
    [
        [],
        [{"Id": "I", "Type": R + "hyperlink", "Target": "picture.bin"}],
        [
            {
                "Id": "I",
                "Type": R + "image",
                "Target": "https://invalid.example/image.png",
                "TargetMode": "External",
            }
        ],
    ],
)
def test_relationship_must_be_internal_image_in_owning_story(links):
    s = build(source(links=links)[0])
    assert not s.complete and s.analysis_text == ""


@pytest.mark.parametrize(
    "binary,mime",
    [
        (b"<svg><text>Hidden requirement</text></svg>", "image/png"),
        (png(), "image/jpeg"),
        (JPEG_BASELINE, "image/png"),
        (png()[:-1], "image/png"),
        (png() + b"TRAILING", "image/png"),
        (JPEG_BASELINE[:-2], "image/jpeg"),
        (JPEG_BASELINE + b"TRAILING", "image/jpeg"),
        (b"\xff\xd8\xff\xd9", "image/jpeg"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><text>Text</text></svg>', "image/svg+xml"),
    ],
)
def test_declared_image_type_or_signature_alone_is_not_coverage(binary, mime):
    s = build(source(binary=binary, mime=mime)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()


def test_old_plain_profile_is_closed_and_rehashed_image_evidence_is_not_authority():
    from ara.docx_analysis.visible_plain_controls import (
        build_plain_control_snapshot,
        map_plain_control_spans,
    )

    raw = source()[0]
    old = build_plain_control_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not old.complete
    s = build(raw)
    error("invalid_snapshot", lambda: map_plain_control_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_inline_image_spans(raw, old, requests=()))
    fake = rehash(
        replace(s, coverage=tuple(c for c in s.coverage if c.code != "inline_raster_boundary"))
    )
    error("invalid_snapshot", lambda: api().map_inline_image_spans(raw, fake, requests=()))


def test_plain_controls_remain_closed_to_images():
    s = build(source("<w:p>" + plain(run(atoms=drawing())) + "</w:p>")[0])
    assert not s.complete and s.analysis_text == ""


def test_header_and_note_images_resolve_relationships_in_their_own_parts():
    relxml = (
        f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="I" Type="{R}image" Target="picture.bin"/></Relationships>'
    ).encode()
    links = [
        {"Id": "H", "Type": R + "header", "Target": "H.xml"},
        {"Id": "Foot", "Type": R + "footnotes", "Target": "Foot.xml"},
    ]
    raw, parts = source(
        p("<w:t>Main</w:t>" + ref()) + section(reference("H")),
        header=p("<w:t>H1</w:t>" + drawing() + "<w:t>H2</w:t>"),
        foot=note("2", content=p("<w:t>N1</w:t>" + drawing() + "<w:t>N2</w:t>")),
        extras={"custom/_rels/H.xml.rels": relxml, "custom/_rels/Foot.xml.rels": relxml},
        links=links,
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Main", "H1", "H2", "N1", "N2"]
    assert len(s.references) == 1
    original(raw, parts, s)
    # A matching ID in main must not substitute for the missing story relationship.
    main_links = links[:1] + [{"Id": "I", "Type": R + "image", "Target": "picture.bin"}]
    bad = source(section(reference("H")), header=p(drawing()), links=main_links)[0]
    assert not build(bad).complete


def test_images_and_note_markers_preserve_nearest_fragment_links():
    links = [
        {"Id": "I", "Type": R + "image", "Target": "picture.bin"},
        {"Id": "Foot", "Type": R + "footnotes", "Target": "Foot.xml"},
    ]
    raw, parts = source(
        p("<w:t>A</w:t>" + drawing() + ref() + drawing() + "<w:t>B</w:t>"),
        foot=note("2", content=p("<w:t>Note</w:t>")),
        links=links,
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["A", "B", "Note"]
    assert s.references[0].before_fragment_id == s.fragments[0].fragment_id
    assert s.references[0].after_fragment_id == s.fragments[1].fragment_id
    original(raw, parts, s)
