"""CRM-shaped Word structures, failure closure and exact source coordinates."""

from xml.etree import ElementTree as E

import pytest
from test_docx_table_catalog import cell, row, table
from test_docx_visible_main import source as minimal_source
from test_docx_visible_main import style
from test_docx_visible_style_lists import fixture, numbered_style
from test_docx_visible_word import W, alter, blocked, build, original, source


def paragraph(raw, change):
    return alter(raw, "word/document.xml", lambda root: change(root.find(".//" + W + "p")))


@pytest.mark.parametrize(
    "prop", ['<w:kern w:val="2"/>', '<w:spacing w:val="-10"/>', "<w:noProof/>"]
)
def test_run_formatting_preserves_hidden_runs_and_coordinates(prop):
    def edit(p):
        p.clear()
        wrapper = E.fromstring(
            '<w:p xmlns:w="'
            + W[1:-1]
            + '"><w:r><w:rPr>'
            + prop
            + "</w:rPr><w:t>Видимый😀</w:t></w:r><w:r><w:rPr>"
            + prop
            + "<w:vanish/></w:rPr><w:t>Скрытый</w:t></w:r></w:p>"
        )
        p.extend(wrapper)

    raw = paragraph(source(), edit)
    s = build(raw)
    assert s.complete and "Видимый😀" in s.analysis_text and "Скрытый" not in s.analysis_text
    original(raw, s)


@pytest.mark.parametrize(
    "prop",
    [
        '<w:kern w:val="-1"/>',
        '<w:spacing w:val="2147483648"/>',
        '<w:noProof w:val="maybe"/>',
        "<w:noProof><w:t>Lost</w:t></w:noProof>",
    ],
)
def test_bad_run_formatting_refused(prop):
    def edit(p):
        run = p.find(W + "r")
        pr = run.find(W + "rPr")
        if pr is None:
            pr = E.Element(W + "rPr")
            run.insert(0, pr)
        pr.append(E.fromstring('<w:x xmlns:w="' + W[1:-1] + '">' + prop + "</w:x>")[0])

    blocked(paragraph(source(), edit))


def test_toc_control_tab_stops_proofing_and_page_cache():
    def edit(p):
        p.clear()
        p.extend(
            E.fromstring(
                '<w:p xmlns:w="' + W[1:-1] + '"><w:pPr><w:tabs>'
                '<w:tab w:val="right" w:pos="9000" w:leader="dot"/></w:tabs></w:pPr>'
                '<w:proofErr w:type="spellStart"/><w:r><w:t>Раздел</w:t>'
                "<w:lastRenderedPageBreak/><w:tab/><w:t>12</w:t></w:r>"
                '<w:proofErr w:type="spellEnd"/></w:p>'
            )
        )

    raw = paragraph(source(), edit)

    def wrap(root):
        body = root.find(W + "body")
        p = body[0]
        body.remove(p)
        sdt = E.Element(W + "sdt")
        pr = E.SubElement(sdt, W + "sdtPr")
        obj = E.SubElement(pr, W + "docPartObj")
        E.SubElement(obj, W + "docPartGallery", {W + "val": "Table of Contents"})
        E.SubElement(obj, W + "docPartUnique")
        E.SubElement(sdt, W + "sdtContent").append(p)
        body.insert(0, sdt)

    raw = alter(raw, "word/document.xml", wrap)
    s = build(raw)
    assert s.complete and "Раздел\t12" in s.analysis_text
    original(raw, s)

    def bad(root):
        E.SubElement(root.find(".//" + W + "sdtPr"), W + "dataBinding")

    blocked(alter(raw, "word/document.xml", bad))


@pytest.mark.parametrize("hidden", [False, True])
def test_mark_character_style_cannot_hide_boundary(hidden):
    props = "<w:rPr><w:vanish/></w:rPr>" if hidden else ""
    raw, _ = minimal_source(
        '<w:p><w:pPr><w:rPr><w:rStyle w:val="CRMMark"/></w:rPr></w:pPr>'
        "<w:r><w:t>Visible</w:t></w:r></w:p>",
        styles=style("CRMMark", props, "character"),
    )
    if hidden:
        blocked(raw)
    else:
        s = build(raw)
        assert s.complete
        original(raw, s)


@pytest.mark.parametrize("extra", [False, True])
def test_empty_merged_continuation_with_mark_formatting(extra):
    mark = '<w:pPr><w:rPr><w:lang w:val="ru-RU"/></w:rPr></w:pPr>'
    text = "<w:r><w:t>Do not discard</w:t></w:r>" if extra else ""
    rows = row(cell(properties='<w:vMerge w:val="restart"/>'))
    rows += row(cell("<w:p>" + mark + text + "</w:p>", "<w:vMerge/>"))
    raw, _ = minimal_source(table(rows, columns=1))
    if extra:
        blocked(raw)
    else:
        s = build(raw)
        assert s.complete
        original(raw, s)


@pytest.mark.parametrize("level", [0, 1])
def test_style_level_must_agree_with_numbering_binding(level):
    styles = numbered_style("S0").replace("<w:numId", f'<w:ilvl w:val="{level}"/><w:numId')
    raw, _ = fixture(styles=styles)
    if level:
        blocked(raw)
    else:
        s = build(raw)
        assert s.complete and s.lists[0].level == 0
        original(raw, s)


@pytest.mark.parametrize("bad", [False, True])
def test_theme_family_closed_extension(bad):
    def edit(root):
        ns = root.tag.rpartition("}")[0] + "}"
        ext = E.SubElement(
            E.SubElement(root, ns + "extLst"),
            ns + "ext",
            {"uri": "{05A4C25C-085E-4340-85A3-A5531E510DB2}"},
        )
        E.SubElement(
            ext,
            "{http://schemas.microsoft.com/office/thememl/2012/main}themeFamily",
            {
                "name": "Office Theme",
                "id": "{2E142A2C-CD16-42D6-873A-C26D2A0506FA}",
                "vid": "{1BDDFF52-6CD6-40A5-AB3C-68EB2F1E4D0A}",
            },
        )
        if bad:
            E.SubElement(ext, ns + "unknown")

    raw = alter(source(), "word/theme/theme1.xml", edit)
    if bad:
        blocked(raw)
    else:
        assert build(raw).complete


@pytest.mark.parametrize("value,pos", [("invalid", "1"), ("right", "bad"), ("right", "2147483648")])
def test_bad_tab_stop_returns_blocked_snapshot(value, pos):
    def edit(p):
        pr = E.Element(W + "pPr")
        p.insert(0, pr)
        E.SubElement(E.SubElement(pr, W + "tabs"), W + "tab", {W + "val": value, W + "pos": pos})

    blocked(paragraph(source(), edit))


@pytest.mark.parametrize(
    "tag,attrs", [("proofErr", {"type": "unknown"}), ("lastRenderedPageBreak", {"bad": "1"})]
)
def test_bad_inert_markers_refused(tag, attrs):
    def edit(p):
        owner = p if tag == "proofErr" else p.find(W + "r")
        E.SubElement(owner, W + tag, {W + k: v for k, v in attrs.items()})

    blocked(paragraph(source(), edit))


def test_storage_and_workers_share_fragment_bound():
    from ara.docx_analysis.storage_codec import CodecLimits
    from ara.docx_analysis_worker.review_fixture import _fragments

    fragments = [
        dict(
            id="vf-" + format(i, "064x"),
            text="Text",
            document="Документ",
            status="active",
            type="фрагмент",
            offset=i,
        )
        for i in range(1024)
    ]
    engine = dict(fragments=fragments, disabled_types=[], dismissed=[])
    assert CodecLimits().max_fragments == 1024
    assert len(_fragments(engine)) == 1024
    engine["fragments"] = fragments + [fragments[0]]
    with pytest.raises(ValueError):
        _fragments(engine)
