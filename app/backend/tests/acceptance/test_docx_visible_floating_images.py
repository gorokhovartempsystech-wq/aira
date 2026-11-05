"""Floating raster anchors are metadata, not in-line text glyphs or text boxes."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_table_catalog import cell, row, table
from test_docx_visible_compatibility import selected
from test_docx_visible_controls import control
from test_docx_visible_inline_images import drawing, source
from test_docx_visible_main import DOC, canonical, codes, payload, rehash
from test_docx_visible_notes import p
from test_docx_visible_plain_controls import plain, run

PROFILE = "docx-analysis/final-visible-floating-images-v1"


def api():
    return import_module("ara.docx_analysis.visible_floating_images")


def build(raw, **kw):
    return api().build_floating_image_snapshot(
        raw,
        **(dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()) | kw),
    )


def anchor(
    *, strict=False, wrap="none", attrs="", behind=True, position=None, props="", pic_props=""
):
    s = drawing(strict=strict, props=props, pic_props=pic_props)
    properties = (
        'simplePos="0" relativeHeight="1" behindDoc="'
        + ("1" if behind else "0")
        + '" locked="0" layoutInCell="1" allowOverlap="1" '
        + attrs
    )
    s = s.replace("<wp:inline ", "<wp:anchor " + properties + " ").replace(
        "</wp:inline>", "</wp:anchor>"
    )
    pos = position or (
        '<wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>0</wp:posOffset></wp:positionV>'
    )
    s = s.replace("<wp:extent", '<wp:simplePos x="0" y="0"/>' + pos + "<wp:extent", 1)
    polygon = (
        '<wp:wrapPolygon edited="0"><wp:start x="0" y="0"/>'
        '<wp:lineTo x="21600" y="0"/><wp:lineTo x="21600" y="21600"/>'
        '<wp:lineTo x="0" y="0"/></wp:wrapPolygon>'
    )
    wraps = {
        "none": "<wp:wrapNone/>",
        "square": '<wp:wrapSquare wrapText="bothSides"/>',
        "top": "<wp:wrapTopAndBottom/>",
        "tight": '<wp:wrapTight wrapText="left">' + polygon + "</wp:wrapTight>",
        "through": '<wp:wrapThrough wrapText="right">' + polygon + "</wp:wrapThrough>",
    }
    return s.replace("<wp:docPr", wraps[wrap] + "<wp:docPr", 1)


def request(f):
    return api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)


def original(raw, parts, s):
    maps = api().map_floating_image_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    for f, m in zip(s.fragments, maps, strict=True):
        texts = []
        for item in m.slices:
            n = resolve(ET.fromstring(parts[item.anchor.part_name]), item.anchor)
            value = n.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            texts.append(value[item.start : item.end])
        assert "".join(texts) == f.text


def error(code, call):
    with pytest.raises(api().VisibleViewError) as e:
        call()
    assert e.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
@pytest.mark.parametrize("wrap", ["none", "square", "top", "tight", "through"])
def test_floating_raster_is_not_an_inline_character_or_a_new_text_boundary(strict, encoding, wrap):
    body = p("<w:t>Я😀</w:t>" + anchor(strict=strict, wrap=wrap) + "<w:t>Text</w:t>")
    raw, parts = source(body, strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.analysis_text == "Я😀Text"
    assert len(s.fragments) == 1 and len(s.fragments[0].pieces) == 2
    assert ("metadata", "floating_raster_reference") in codes(s)
    assert ("metadata", "inline_raster_boundary") not in codes(s)
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and s == build(raw)
    original(raw, parts, s)


def test_inline_and_floating_objects_preserve_their_distinct_boundaries():
    raw, parts = source(
        p(
            "<w:t>A</w:t>"
            + anchor()
            + "<w:t>B</w:t>"
            + drawing()
            + "<w:t>C</w:t>"
            + anchor()
            + "<w:t>D</w:t>"
        )
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["AB", "CD"]
    assert len([c for c in s.coverage if c.code == "floating_raster_reference"]) == 2
    assert len([c for c in s.coverage if c.code == "inline_raster_boundary"]) == 1
    original(raw, parts, s)


@pytest.mark.parametrize("wrapper", ["rich", "selected", "table"])
def test_original_anchor_paths_and_real_cell_ownership_survive_wrappers(wrapper):
    body = p("<w:t>One</w:t>" + selected(anchor(wrap="square", behind=False)) + "<w:t>Two</w:t>")
    if wrapper == "rich":
        body = control(body)
    elif wrapper == "selected":
        body = selected(body)
    else:
        body = table(row(cell(body)), 1)
    raw, parts = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "OneTwo"
    original(raw, parts, s)
    c = next(c for c in s.coverage if c.code == "floating_raster_reference")
    assert resolve(ET.fromstring(parts[c.part_name]), c.anchor).tag.endswith("}drawing")
    if wrapper == "table":
        f = s.fragments[0]
        assert resolve(ET.fromstring(parts[f.flow_anchor.part_name]), f.flow_anchor).tag.endswith(
            "}tc"
        )


@pytest.mark.parametrize(
    "horizontal,vertical",
    [
        ("page", "page"),
        ("margin", "margin"),
        ("character", "line"),
        ("insideMargin", "outsideMargin"),
    ],
)
def test_position_alignment_is_metadata_and_never_reorders_text(horizontal, vertical):
    position = (
        f'<wp:positionH relativeFrom="{horizontal}"><wp:align>center</wp:align></wp:positionH>'
    )
    position += (
        f'<wp:positionV relativeFrom="{vertical}"><wp:align>bottom</wp:align></wp:positionV>'
    )
    raw, parts = source(p("<w:t>A</w:t>" + anchor(position=position) + "<w:t>B</w:t>"))
    s = build(raw)
    assert s.complete and s.analysis_text == "AB"
    original(raw, parts, s)


@pytest.mark.parametrize("kind", ["anchor", "doc", "picture", "run"])
def test_hidden_objects_still_validate_and_do_not_create_synthetic_characters(kind):
    obj = anchor(
        attrs='hidden="1"' if kind == "anchor" else "",
        props='hidden="true"' if kind == "doc" else "",
        pic_props='hidden="1"' if kind == "picture" else "",
    )
    body = (
        "<w:p>"
        + run("A")
        + run(props="<w:vanish/>" if kind == "run" else "", atoms=obj)
        + run("B")
        + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "AB"
    invalid = body.replace('<a:blip r:embed="I"/>', '<a:blip r:embed="absent"/>')
    assert not build(source(invalid)[0]).complete


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.replace('behindDoc="1"', 'behindDoc="0"'),
        lambda x: x.replace('relativeHeight="1"', ""),
        lambda x: x.replace('locked="0"', 'locked="off"'),
        lambda x: x.replace('<wp:simplePos x="0" y="0"/>', ""),
        lambda x: x.replace(
            "<wp:posOffset>0</wp:posOffset>",
            "<wp:posOffset>0</wp:posOffset><wp:align>center</wp:align>",
            1,
        ),
        lambda x: x.replace('relativeFrom="column"', 'relativeFrom="paragraph"'),
        lambda x: x.replace(
            "<wp:posOffset>0</wp:posOffset>", "<wp:posOffset>2147483648</wp:posOffset>", 1
        ),
        lambda x: x.replace(
            "<wp:wrapNone/>", '<wp:wrapNone/><wp:wrapSquare wrapText="bothSides"/>'
        ),
        lambda x: x.replace("<wp:wrapNone/>", "<wp:unknown/>"),
        lambda x: x.replace("<wp:wrapNone/>", "<wp:wrapSquare/>"),
        lambda x: x.replace('name="Synthetic image"', 'name="Synthetic image" descr="Private"'),
        lambda x: x.replace("<pic:cNvPicPr/>", "<pic:cNvPicPr><w:txbxContent/></pic:cNvPicPr>"),
        lambda x: x.replace("wp:anchor", "wp:unknown"),
    ],
)
def test_unknown_malformed_and_unproved_foreground_overlay_remain_atomic(change):
    s = build(source(p("<w:t>Private</w:t>" + change(anchor())))[0])
    assert (
        not s.complete
        and s.analysis_text == ""
        and s.fragments == s.paragraphs == s.runs == s.references == ()
    )
    assert "Private" not in repr(s)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.replace('<wp:start x="0" y="0"/>', ""),
        lambda x: x.replace('<wp:lineTo x="21600" y="0"/>', "").replace(
            '<wp:lineTo x="21600" y="21600"/>', ""
        ),
        lambda x: x.replace('wrapText="left"', 'wrapText="wrong"'),
        lambda x: x.replace('edited="0"', 'edited="off"'),
        lambda x: x.replace(
            '<wp:lineTo x="21600" y="0"/>',
            '<wp:lineTo x="21600" y="0"><w:t>Hidden</w:t></wp:lineTo>',
        ),
    ],
)
def test_wrap_polygon_is_closed_metadata_and_not_an_unread_text_container(change):
    s = build(source(p(change(anchor(wrap="tight"))))[0])
    assert not s.complete and s.fragments == ()


def test_empty_and_deleted_floating_images_do_not_invent_requirements():
    raw = source(p(anchor() + anchor()))[0]
    s = build(raw)
    assert s.complete and s.fragments == () and s.analysis_text == ""
    assert api().map_floating_image_spans(raw, s, requests=()) == ()
    body = (
        '<w:p><w:del w:id="1">'
        + run(atoms=anchor().replace("wp:anchor", "wp:unknown"))
        + "</w:del>"
        + run("Kept")
        + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Kept"
    assert ("excluded", "unreferenced_raster_image") in codes(s)


def test_inline_profile_stays_closed_to_anchors_and_rehashing_is_not_authority():
    from ara.docx_analysis.visible_inline_images import (
        build_inline_image_snapshot,
        map_inline_image_spans,
    )

    raw = source(p("<w:t>A</w:t>" + anchor() + "<w:t>B</w:t>"))[0]
    old = build_inline_image_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not old.complete
    s = build(raw)
    error("invalid_snapshot", lambda: map_inline_image_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_floating_image_spans(raw, old, requests=()))
    fake = rehash(
        replace(s, coverage=tuple(c for c in s.coverage if c.code != "floating_raster_reference"))
    )
    error("invalid_snapshot", lambda: api().map_floating_image_spans(raw, fake, requests=()))


def test_plain_controls_remain_closed_to_floating_images():
    s = build(source("<w:p>" + plain(run(atoms=anchor())) + "</w:p>")[0])
    assert not s.complete and s.analysis_text == ""
