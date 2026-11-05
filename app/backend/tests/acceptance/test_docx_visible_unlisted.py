"""Own-template unlisted text and source-proven unused numbering, not list admission."""

import io
import zipfile
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_visible_compatibility import selected as raw_selected
from test_docx_visible_main import DOC, SR, R, S, W, canonical, codes, payload, rehash, style
from test_docx_visible_main import source as simple_source
from test_docx_visible_plain_controls import run

from ara.docx_package.creation import NewParagraph, create_docx

PROFILE = "docx-analysis/final-visible-unlisted-v1"
STYLE_PROFILE = "docx-visibility/mc-pagination-styles-v1"
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
PART = "custom/Numbers.xml"
LEVEL = (
    '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
    '<w:lvlText w:val="%1."/></w:lvl>'
)
DEFS = (
    '<w:abstractNum w:abstractNumId="0">'
    + LEVEL
    + '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
)
NUMPR = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'


def selected(content):
    return raw_selected(content).replace(
        "<mc:AlternateContent",
        "<mc:AlternateContent "
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:x="urn:future"',
        1,
    )


def api():
    return import_module("ara.docx_analysis.visible_unlisted")


def build(raw, **kw):
    return api().build_unlisted_snapshot(
        raw,
        **(dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()) | kw),
    )


def source(
    body=None, definitions=DEFS, *, strict=False, encoding="utf-8", styles=None, links=None, **kw
):
    body = (
        "<w:p><w:pPr><w:widowControl/></w:pPr>" + run("A😀Я") + "</w:p>" if body is None else body
    )
    raw = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:numbering xmlns:w="{S if strict else W}">{definitions}</w:numbering>'
    ).encode(encoding)
    package, _ = simple_source(
        body,
        styles,
        strict=strict,
        encoding=encoding,
        extra_parts={PART: raw} | kw.pop("extra_parts", {}),
        extra_types={PART: MIME} | kw.pop("extra_types", {}),
        links=[{"Id": "N", "Type": (SR if strict else R) + "numbering", "Target": "Numbers.xml"}]
        if links is None
        else links,
        **kw,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        return package, {name: archive.read(name) for name in archive.namelist()}


def original(raw, parts, s):
    reqs = tuple(
        api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text) for f in s.fragments
    )
    maps = api().map_unlisted_spans(raw, s, requests=reqs)
    for f, mapped in zip(s.fragments, maps, strict=True):
        values = []
        for item in mapped.slices:
            n = resolve(ET.fromstring(parts[item.anchor.part_name]), item.anchor)
            text = n.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            values.append(text[item.start : item.end])
        assert "".join(values) == f.text


def error(code, call):
    with pytest.raises(api().VisibleViewError) as exc:
        call()
    assert exc.value.code == code


@pytest.mark.parametrize("kind", ["body", "heading1", "heading2", "heading3"])
def test_actual_aira_template_plain_paragraphs_roundtrip_without_rewriting(kind):
    raw = create_docx((NewParagraph("A😀\tЯ\nB", kind),))
    before = sha256(raw).hexdigest()
    s = build(raw)
    assert s.complete and s.analysis_text == "A😀\tЯ\nB" and s.profile == PROFILE
    assert s.style_context.profile == STYLE_PROFILE
    assert ("excluded", "unused_numbering_definition") in codes(s)
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and s == build(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        original(raw, {n: z.read(n) for n in z.namelist()}, s)
    assert sha256(raw).hexdigest() == before


def test_empty_own_template_does_not_invent_a_numbered_requirement():
    raw = create_docx(())
    s = build(raw)
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert api().map_unlisted_spans(raw, s, requests=()) == ()


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_custom_part_names_utf16_and_original_pagination_style_anchors(strict, encoding):
    styles = selected(
        style("Normal", '<w:pPr><w:widowControl w:val="off"/></w:pPr>', attrs='w:default="1"')
    )
    raw, parts = source(strict=strict, encoding=encoding, styles=styles)
    s = build(raw)
    assert s.complete and s.analysis_text == "A😀Я" and s.style_context.profile == STYLE_PROFILE
    original(raw, parts, s)
    assert s.style_context.styles_part == "custom/Styles.xml"


@pytest.mark.parametrize(
    "value",
    [
        "",
        ' w:val="on"',
        ' w:val="off"',
        ' w:val="true"',
        ' w:val="false"',
        ' w:val="1"',
        ' w:val="0"',
    ],
)
def test_current_widow_control_is_only_pagination_metadata(value):
    prop = "<w:widowControl" + value + "/>"
    styles = (
        "<w:docDefaults><w:pPrDefault><w:pPr>" + prop + "</w:pPr></w:pPrDefault></w:docDefaults>"
    )
    raw, parts = source("<w:p><w:pPr>" + prop + "</w:pPr>" + run("Kept") + "</w:p>", styles=styles)
    s = build(raw)
    assert s.complete and s.analysis_text == "Kept"
    original(raw, parts, s)


@pytest.mark.parametrize(
    "prop",
    [
        '<w:widowControl w:val="yes"/>',
        '<w:widowControl w:other="0"/>',
        "<w:widowControl>text</w:widowControl>",
        "<w:widowControl><w:t>x</w:t></w:widowControl>",
        "<w:widowControl/><w:widowControl/>",
    ],
)
def test_invalid_new_property_never_hides_text_or_passes_in_styles(prop):
    direct = source("<w:p><w:pPr>" + prop + "</w:pPr>" + run("Private") + "</w:p>")[0]
    inherited = source(
        styles=style("Normal", "<w:pPr>" + prop + "</w:pPr>", attrs='w:default="1"')
    )[0]
    for raw in (direct, inherited):
        s = build(raw)
        assert (
            not s.complete
            and s.analysis_text == ""
            and s.fragments == s.runs == s.paragraphs == s.references == ()
        )
        assert ("excluded", "unused_numbering_definition") not in codes(s)
        assert "Private" not in repr(s)


@pytest.mark.parametrize("kind", ["bullet", "numbered"])
def test_own_template_active_lists_remain_an_explicit_gate(kind):
    s = build(create_docx((NewParagraph("Private", kind),)))
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    assert ("excluded", "unused_numbering_definition") not in codes(s)


@pytest.mark.parametrize("placement", ["direct", "style", "default", "reverse"])
def test_no_unused_assertion_when_numbering_can_be_applied(placement):
    body = "<w:p>" + run("Private") + "</w:p>"
    styles = None
    definitions = DEFS
    if placement == "direct":
        body = "<w:p><w:pPr>" + NUMPR + "</w:pPr>" + run("Private") + "</w:p>"
    elif placement == "style":
        styles = style("Normal", "<w:pPr>" + NUMPR + "</w:pPr>", attrs='w:default="1"')
    elif placement == "default":
        styles = (
            "<w:docDefaults><w:pPrDefault><w:pPr>"
            + NUMPR
            + "</w:pPr></w:pPrDefault></w:docDefaults>"
        )
    else:
        styles = style("Normal", attrs='w:default="1"')
        definitions = DEFS.replace("<w:lvlText", '<w:pStyle w:val="Normal"/><w:lvlText')
    s = build(source(body, definitions, styles=styles)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    assert ("excluded", "unused_numbering_definition") not in codes(s)


@pytest.mark.parametrize(
    "defs",
    [
        DEFS.replace('w:numId="1"', 'w:numId="0"'),
        DEFS.replace('w:abstractNumId="0"', 'w:abstractNumId="2147483648"'),
        DEFS.replace('w:ilvl="0"', 'w:ilvl="9"'),
        DEFS.replace('<w:num w:numId="1">', '<w:num w:numId="1" w:extra="0">'),
        DEFS.replace('<w:abstractNumId w:val="0"/>', '<w:abstractNumId w:val="2"/>'),
        DEFS + DEFS,
        DEFS.replace(LEVEL, LEVEL + LEVEL),
        DEFS.replace("<w:lvlText", '<w:pStyle w:val="Normal"/><w:lvlText'),
        DEFS.replace(LEVEL, '<w:styleLink w:val="List"/>' + LEVEL),
        DEFS.replace(LEVEL, '<w:numStyleLink w:val="List"/>' + LEVEL),
        DEFS.replace(LEVEL, selected(LEVEL)),
        DEFS.replace('<w:start w:val="1"/>', '<w:start w:val="1">Secret</w:start>'),
        DEFS.replace('<w:start w:val="1"/>', "<w:unknown/>"),
        DEFS.replace('<w:start w:val="1"/>', '<w:start w:val="1"/><w:start w:val="1"/>'),
        DEFS.replace('<w:start w:val="1"/>', "").replace(
            "</w:lvl>", '<w:start w:val="1"/></w:lvl>'
        ),
    ],
)
def test_numbering_envelope_is_closed_even_if_direct_content_looks_unlisted(defs):
    s = build(source(definitions=defs)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    assert ("excluded", "unused_numbering_definition") not in codes(s)


def test_unused_overrides_and_unlinked_part_are_accounted_only_after_closure():
    defs = DEFS.replace(
        "</w:num>",
        '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="7"/>'
        + LEVEL
        + "</w:lvlOverride></w:num>",
    )
    raw, parts = source(definitions=defs, links=[])
    s = build(raw)
    assert s.complete and s.analysis_text == "A😀Я"
    assert ("excluded", "unused_numbering_definition") in codes(s)
    original(raw, parts, s)
    bad = source("<w:p>" + run("Secret", props="<w:unknown/>") + "</w:p>", defs, links=[])[0]
    assert not build(bad).complete
    assert ("excluded", "unused_numbering_definition") not in codes(build(bad))


def test_inherited_visibility_and_old_profile_boundaries_are_unchanged():
    from ara.docx_analysis.visible_floating_images import (
        build_floating_image_snapshot,
        map_floating_image_spans,
    )

    styles = style(
        "Normal",
        "<w:pPr><w:widowControl/></w:pPr>",
        attrs='w:default="1"',
    ) + style("HiddenChar", "<w:rPr><w:vanish/></w:rPr>", kind="character")
    raw, _ = source(
        "<w:p>"
        + run("Hidden", props='<w:rStyle w:val="HiddenChar"/>')
        + run("Visible", props='<w:rStyle w:val="HiddenChar"/><w:vanish w:val="0"/>')
        + "</w:p>",
        styles=styles,
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "Visible"
    old = build_floating_image_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not old.complete
    error("invalid_snapshot", lambda: map_floating_image_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_unlisted_spans(raw, old, requests=()))
    fake = rehash(
        replace(s, coverage=tuple(c for c in s.coverage if c.code != "unused_numbering_definition"))
    )
    error("invalid_snapshot", lambda: api().map_unlisted_spans(raw, fake, requests=()))
