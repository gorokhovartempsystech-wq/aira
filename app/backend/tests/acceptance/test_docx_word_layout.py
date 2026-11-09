"""Ordinary Word layout cannot hide requirements or rewrite their source package."""

from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_visible_main import rehash, style
from test_docx_visible_main import source as minimal
from test_docx_visible_style_lists import fixture, numbered_style
from test_docx_visible_word import blocked, build, original, parts

from ara.docx_analysis.visible_word import VisibleViewError, map_word_span

BORDER = '<w:pBdr><w:bottom w:val="single" w:sz="8" w:space="1" w:color="auto"/></w:pBdr>'


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_optional_hyphen_and_positional_tab_keep_exact_coordinates(strict, encoding):
    raw, _ = minimal(
        "<w:p><w:r><w:t>тре</w:t><w:softHyphen/><w:t>бование😀</w:t>"
        '<w:ptab w:alignment="right" w:relativeTo="margin" w:leader="dot"/>'
        "<w:t>готово</w:t></w:r></w:p>",
        strict=strict,
        encoding=encoding,
    )
    before = parts(raw)
    s = build(raw)
    assert s.complete and s.analysis_text == "требование😀\tготово"
    original(raw, s)
    assert any(c.code == "optional_hyphen" for c in s.coverage)
    assert parts(raw) == before


@pytest.mark.parametrize("hidden", [False, True])
def test_nonbreaking_hyphen_has_original_atom_and_visibility(hidden):
    props = "<w:rPr><w:vanish/></w:rPr>" if hidden else ""
    raw, _ = minimal(
        "<w:p><w:r><w:t>Проверить </w:t></w:r><w:r>"
        + props
        + "<w:t>веб</w:t><w:noBreakHyphen/><w:t>сервис😀</w:t></w:r></w:p>"
    )
    s = build(raw)
    assert s.complete and s.analysis_text == (
        "Проверить " if hidden else "Проверить веб\u2011сервис😀"
    )
    f = s.fragments[0]
    mapped = map_word_span(
        raw, s, fragment_id=f.fragment_id, start=0, end=len(f.text), quote=f.text
    )
    strings = []
    for item in mapped.slices:
        node = resolve(ET.fromstring(parts(raw)[item.anchor.part_name]), item.anchor)
        if item.kind == "nonbreaking_hyphen":
            assert node.tag.endswith("}noBreakHyphen") and (item.start, item.end) == (0, 1)
            strings.append("\u2011")
        else:
            strings.append(node.text[item.start : item.end])
    assert "".join(strings) == f.text
    if not hidden:
        changed = replace(f, text=f.text.replace("\u2011", "-"))
        forged = rehash(replace(s, fragments=(changed,), analysis_text=changed.text))
        with pytest.raises(VisibleViewError):
            map_word_span(raw, forged, fragment_id=f.fragment_id, start=0, end=1, quote="П")


@pytest.mark.parametrize("where", ["direct", "style"])
def test_paragraph_border_is_layout_only(where):
    props = BORDER if where == "direct" else '<w:pStyle w:val="Title"/>'
    styles = style("Title", "<w:pPr>" + BORDER + "</w:pPr>") if where == "style" else None
    raw, _ = minimal(
        "<w:p><w:pPr>" + props + "</w:pPr><w:r><w:t>Требование😀</w:t></w:r></w:p>", styles=styles
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "Требование😀"
    original(raw, s)


@pytest.mark.parametrize("prop", ["", '<w:ilvl w:val="0"/>'])
def test_style_numpr_without_instance_does_not_invent_numbering(prop):
    raw, _ = minimal(
        '<w:p><w:pPr><w:pStyle w:val="Subtitle"/></w:pPr><w:r><w:t>Text</w:t></w:r></w:p>',
        styles=style("Subtitle", "<w:pPr><w:numPr>" + prop + "</w:numPr></w:pPr>"),
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "Text" and s.lists == ()
    original(raw, s)


@pytest.mark.parametrize("level", [0, 1])
def test_partial_style_numpr_inherits_instance_but_preserves_level_agreement(level):
    styles = numbered_style("Base") + style(
        "S0",
        f'<w:basedOn w:val="Base"/><w:pPr><w:numPr><w:ilvl w:val="{level}"/></w:numPr></w:pPr>',
    )
    raw, _ = fixture(styles=styles)
    if level:
        blocked(raw)
    else:
        s = build(raw)
        assert s.complete and len(s.lists) == 1 and s.lists[0].label == "1."
        original(raw, s)


@pytest.mark.parametrize(
    "atom",
    [
        '<w:softHyphen w:bad="1"/>',
        "<w:softHyphen><w:t>lost</w:t></w:softHyphen>",
        '<w:noBreakHyphen w:bad="1"/>',
        "<w:noBreakHyphen>lost</w:noBreakHyphen>",
        '<w:ptab w:alignment="wrong" w:relativeTo="margin" w:leader="none"/>',
        '<w:ptab w:alignment="left" w:relativeTo="margin"/>',
    ],
)
def test_malformed_layout_atoms_refuse_entire_analysis(atom):
    raw, _ = minimal("<w:p><w:r><w:t>Visible</w:t>" + atom + "</w:r></w:p>")
    blocked(raw)


@pytest.mark.parametrize(
    "bad",
    [
        "<w:pBdr><w:t>lost</w:t></w:pBdr>",
        '<w:pBdr><w:bottom w:val="single"><w:t>lost</w:t></w:bottom></w:pBdr>',
        '<w:pBdr><w:bottom w:val="single"/><w:bottom w:val="single"/></w:pBdr>',
        '<w:pBdr><w:bottom w:val="unknown"/></w:pBdr>',
        '<w:pBdr><w:bottom w:val="single" w:space="-1"/></w:pBdr>',
    ],
)
@pytest.mark.parametrize("where", ["direct", "style"])
def test_malformed_borders_cannot_discard_content(bad, where):
    props = bad if where == "direct" else '<w:pStyle w:val="Title"/>'
    styles = style("Title", "<w:pPr>" + bad + "</w:pPr>") if where == "style" else None
    raw, _ = minimal(
        "<w:p><w:pPr>" + props + "</w:pPr><w:r><w:t>Visible</w:t></w:r></w:p>", styles=styles
    )
    blocked(raw)
