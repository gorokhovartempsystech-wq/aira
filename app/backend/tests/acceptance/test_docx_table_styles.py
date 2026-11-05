"""Frozen neutral-table-style proof acceptance from literal styles XML."""

import json
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from docx_projection_fixtures import package
from test_docx_visibility_styles import MIME, R, W, fixture, style

PROFILE = "docx-table-styles/neutral-current-v1"
REGIONS = (
    "wholeTable",
    "firstRow",
    "lastRow",
    "firstCol",
    "lastCol",
    "band1Vert",
    "band2Vert",
    "band1Horz",
    "band2Horz",
    "neCell",
    "nwCell",
    "seCell",
    "swCell",
)


def api():
    return import_module("ara.docx_analysis.table_styles")


def table_style(identity="A", content="", attrs=""):
    return style(identity, content, kind="table", attrs=attrs)


def read(raw, **kwargs):
    return api().read_table_style_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def index(catalog):
    return {s.style_id: s for s in catalog.styles}


def payload(catalog):
    value = asdict(catalog)
    value.pop("catalog_sha256")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def error(code, call):
    with pytest.raises(api().TableStyleError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_neutral_ancestry_regions_and_exact_source_provenance(strict, encoding):
    content = table_style(
        "Z",
        '<w:name w:val="Synthetic name"/><w:rPr><w:b/></w:rPr>'
        '<w:tblPr><w:tblBorders><w:top w:val="single"/></w:tblBorders></w:tblPr>',
        attrs='w:default="true"',
    )
    content += table_style(
        "A",
        '<w:basedOn w:val="Z"/><w:tblStylePr w:type="firstRow">'
        '<w:rPr><w:color w:val="223344"/></w:rPr>'
        '<w:tcPr><w:shd w:fill="FFFFFF"/></w:tcPr></w:tblStylePr>',
    )
    raw, xml = fixture(content, strict=strict, encoding=encoding)
    c = read(raw)
    assert c.profile == PROFILE and c.status == "ready" and c.issues == ()
    assert c.default_table_style == "Z" and c.styles_part == "custom/Visibility.xml"
    assert [s.style_id for s in c.styles] == ["A", "Z"]
    a, z = c.styles
    assert a.status == z.status == "neutral" and a.issues == z.issues == ()
    assert a.based_on == "Z" and z.based_on is None and z.is_default and not a.is_default
    assert [x.path for x in a.chain] == [(1,), (0,)]
    assert z.chain == (z.anchor,)
    assert [(r.kind, r.anchor.path) for r in a.regions] == [("firstRow", (1, 1))]
    assert [x.path for x in z.metadata] == [
        (0, 0),
        (0, 1),
        (0, 1, 0),
        (0, 2),
        (0, 2, 0),
        (0, 2, 0, 0),
    ]
    root = ET.fromstring(xml)
    for anchor in a.metadata + z.metadata + a.chain + (a.regions[0].anchor,):
        assert anchor.source_sha256 == sha256(raw).hexdigest()
        assert anchor.part_name == c.styles_part
        node = root
        for position in anchor.path:
            node = node[position]
        assert node.tag.startswith("{")
    assert [x.path for x in a.metadata] == [(1, 1, 0), (1, 1, 0, 0), (1, 1, 1), (1, 1, 1, 0)]
    context = import_module("ara.docx_analysis.visibility").read_style_context(
        raw, source_sha256=sha256(raw).hexdigest()
    )
    assert c.style_context_sha256 == context.context_sha256
    assert c.catalog_sha256 == sha256(payload(c)).hexdigest()
    assert read(raw) == c
    assert not hasattr(c, "complete") and not hasattr(c, "analysis_text")
    assert sha256(raw).hexdigest() == c.source_sha256
    with pytest.raises(FrozenInstanceError):
        a.status = "changed"
    assert not hasattr(a, "__dict__")


def test_all_conditional_regions_are_checked_not_only_first_row():
    content = "".join(
        f'<w:tblStylePr w:type="{kind}"><w:rPr><w:b/></w:rPr></w:tblStylePr>' for kind in REGIONS
    )
    s = read(fixture(table_style(content=content))[0]).styles[0]
    assert s.status == "neutral" and tuple(r.kind for r in s.regions) == REGIONS
    for kind in REGIONS:
        bad = content.replace(
            f'<w:tblStylePr w:type="{kind}"><w:rPr><w:b/>',
            f'<w:tblStylePr w:type="{kind}"><w:rPr><w:vanish/>',
        )
        s = read(fixture(table_style(content=bad))[0]).styles[0]
        assert s.status == "blocked" and s.issues[0].code == "unsupported_table_style"
        assert s.chain == s.metadata == s.regions == () and s.based_on is None


def test_format_metadata_and_ui_hidden_are_not_run_visibility():
    content = (
        '<w:hidden/><w:semiHidden/><w:qFormat/><w:link w:val="missing"/>'
        '<w:next w:val="missing"/><w:aliases w:val="Synthetic aliases"/>'
        '<w:uiPriority w:val="12"/><w:rsid w:val="1A2B3C4D"/>'
        '<w:rPr><w:b/><w:i/><w:u w:val="single"/><w:rFonts w:ascii="Arial"/>'
        '<w:lang w:val="ru-RU"/><w:sz w:val="22"/></w:rPr>'
        '<w:pPr><w:spacing w:after="0"/><w:keepNext/><w:jc w:val="left"/></w:pPr>'
        '<w:tblPr><w:tblW w:type="auto"/><w:tblLook w:val="04A0"/>'
        '<w:tblStyleRowBandSize w:val="2"/><w:tblStyleColBandSize w:val="1"/>'
        '<w:bidiVisual w:val="false"/><w:tblCellMar><w:start w:w="100"/>'
        "</w:tblCellMar></w:tblPr><w:trPr><w:cantSplit/><w:tblHeader/>"
        '<w:trHeight w:val="100"/></w:trPr><w:tcPr><w:tcFitText/><w:hideMark/>'
        '<w:noWrap/><w:textDirection w:val="tbRl"/><w:tcBorders><w:bottom/>'
        '</w:tcBorders><w:tcMar><w:top w:w="100"/></w:tcMar></w:tcPr>'
    )
    c = read(fixture(table_style(content=content))[0])
    assert c.styles[0].status == "neutral" and c.styles[0].based_on is None
    assert len(c.styles[0].metadata) > 30


@pytest.mark.parametrize(
    "content",
    [
        '<w:rPr><w:vanish w:val="false"/></w:rPr>',
        "<w:rPr><w:specVanish/></w:rPr>",
        "<w:rPr><w:webHidden/></w:rPr>",
        '<w:rPr><w:rStyle w:val="Other"/></w:rPr>',
        '<w:pPr><w:pStyle w:val="Other"/></w:pPr>',
        "<w:pPr><w:numPr/></w:pPr>",
        "<w:pPr><w:rPr><w:vanish/></w:rPr></w:pPr>",
        '<w:tblPr><w:tblStyle w:val="Other"/></w:tblPr>',
        "<w:tblPr><w:tblpPr/></w:tblPr>",
        '<w:trPr><w:hidden w:val="false"/></w:trPr>',
        '<w:trPr><w:gridBefore w:val="1"/></w:trPr>',
        '<w:tcPr><w:gridSpan w:val="2"/></w:tcPr>',
        "<w:tcPr><w:vMerge/></w:tcPr>",
        "<w:tcPr><w:hMerge/></w:tcPr>",
        '<w:tcPr><w:cellDel w:id="1"/></w:tcPr>',
        '<w:rPr><w:rPrChange w:id="1"><w:rPr/></w:rPrChange></w:rPr>',
        '<w:tblPr><w:tblPrChange w:id="1"><w:tblPr/></w:tblPrChange></w:tblPr>',
        "<w:unknown/>",
        "<w:rPr><w:b/><w:b/></w:rPr>",
        "<w:rPr/><w:rPr/>",
        '<w:tblStylePr w:type="firstRow"/><w:tblStylePr w:type="firstRow"/>',
        '<w:tblStylePr w:type="bogus"/>',
        "<w:tblStylePr/>",
        '<w:tblStylePr w:type="firstRow"><w:basedOn w:val="Other"/></w:tblStylePr>',
        '<w:tblStylePr w:type="firstRow" w:extra="x"/>',
        "<w:tcPr><w:tcBorders><w:top/><w:top/></w:tcBorders></w:tcPr>",
        "<w:tcPr><w:tcMar><w:unknown/></w:tcMar></w:tcPr>",
        "<w:rPr><w:b><w:vanish/></w:b></w:rPr>",
        "<w:rPr><w:b>PAYLOAD</w:b></w:rPr>",
        "<w:rPr><s:b/></w:rPr>",
        '<w:rPr><w:b s:val="true"/></w:rPr>',
        '<w:trPr><w:cantSplit w:val="TRUE"/></w:trPr>',
        '<w:basedOn w:val="B"/><w:basedOn w:val="C"/>',
        '<w:uiPriority w:val="-1"/>',
    ],
)
def test_unknown_or_semantic_property_blocks_only_own_definition(content):
    c = read(fixture(table_style("A", content) + table_style("B"))[0])
    assert c.status == "ready" and index(c)["B"].status == "neutral"
    a = index(c)["A"]
    assert a.status == "blocked" and a.issues[0].code == "unsupported_table_style"
    assert a.issues[0].anchor == a.anchor and a.issues[0].style_id == "A"
    assert a.chain == a.regions == a.metadata == () and a.based_on is None


@pytest.mark.parametrize(
    "definitions,code",
    [
        (table_style("A", '<w:basedOn w:val="missing"/>'), "missing_base_style"),
        (table_style("A", '<w:basedOn w:val="P"/>') + style("P"), "base_style_type_mismatch"),
        (table_style("A", '<w:basedOn w:val="A"/>'), "style_cycle"),
        (
            table_style("A", '<w:basedOn w:val="B"/>')
            + table_style("B", '<w:basedOn w:val="C"/>')
            + table_style("C", '<w:basedOn w:val="B"/>'),
            "style_cycle",
        ),
        (
            table_style("A", '<w:basedOn w:val="B"/>')
            + table_style("B", "<w:rPr><w:vanish/></w:rPr>"),
            "unresolved_base_style",
        ),
    ],
)
def test_missing_wrong_kind_cycle_or_nonneutral_ancestor_is_not_guessed(definitions, code):
    c = read(fixture(definitions + table_style("Safe"))[0])
    assert c.status == "ready" and index(c)["Safe"].status == "neutral"
    a = index(c)["A"]
    assert a.status == "blocked" and a.chain == () and a.issues[0].code == code


def test_false_override_never_cancels_unsupported_ancestor():
    c = read(
        fixture(
            table_style("A", '<w:basedOn w:val="B"/><w:rPr><w:vanish w:val="false"/></w:rPr>')
            + table_style("B", "<w:rPr><w:vanish/></w:rPr>")
        )[0]
    )
    assert all(s.status == "blocked" and s.chain == () for s in c.styles)


def test_absent_and_bad_default_are_distinct_and_do_not_poison_unrelated_styles():
    for raw in (package("<w:p/>")[0], fixture(style())[0]):
        c = read(raw)
        assert c.status == "absent" and c.styles == c.issues == ()
        assert c.default_table_style is None
        assert c.catalog_sha256 == sha256(payload(c)).hexdigest()
    raw = fixture(
        table_style("Bad", "<w:unknown/>", attrs='w:default="1"')
        + table_style("Good")
        + style("Opaque", "<w:unknown/>", kind="numbering")
    )[0]
    c = read(raw)
    assert c.status == "ready" and c.default_table_style == "Bad"
    assert index(c)["Bad"].status == "blocked" and index(c)["Good"].status == "neutral"
    assert "Opaque" not in index(c)


@pytest.mark.parametrize(
    "content",
    [
        table_style() + table_style(),
        table_style(attrs='w:default="1"') + table_style("B", attrs='w:default="true"'),
        '<w:style w:type="table"/>',
        "PAYLOAD" + table_style(),
        "<w:docDefaults><w:rPrDefault><w:rPr><w:unknown/></w:rPr></w:rPrDefault></w:docDefaults>"
        + table_style(),
    ],
)
def test_global_style_context_failure_never_publishes_partial_definitions(content):
    c = read(fixture(content)[0])
    assert c.status == "blocked" and c.styles == () and c.default_table_style is None
    assert len(c.issues) == 1 and c.issues[0].code == "style_context_blocked"
    assert c.issues[0].anchor.path == () and c.issues[0].style_id is None
    assert c.catalog_sha256 == sha256(payload(c)).hexdigest()


@pytest.mark.parametrize("variant", ["orphan", "extra", "external", "duplicate", "wrong_mime"])
def test_ambiguous_styles_source_has_no_table_proof(variant):
    xml = f'<w:styles xmlns:w="{W}">{table_style()}</w:styles>'.encode()
    parts, types = {"word/styles.xml": xml}, {"word/styles.xml": MIME}
    link = dict(Id="s", Type=R + "styles", Target="styles.xml")
    links = [link]
    if variant == "orphan":
        links = []
    elif variant == "extra":
        parts["word/other.xml"] = xml
        types["word/other.xml"] = MIME
    elif variant == "external":
        links = [dict(link, Target="https://example.invalid/styles", TargetMode="External")]
    elif variant == "duplicate":
        links.append(dict(link, Id="s2"))
    else:
        types["word/styles.xml"] = "application/xml"
    c = read(package("<w:p/>", extra_parts=parts, extra_types=types, links=links)[0])
    assert c.status == "blocked" and c.styles == () and c.styles_part is None
    assert c.issues[0].code == "style_context_blocked" and c.issues[0].anchor is None
