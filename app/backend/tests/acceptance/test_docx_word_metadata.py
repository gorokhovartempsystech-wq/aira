"""Word identities, column bookmarks and explicit LTR formatting preserve literal text."""

import pytest
from test_docx_visible_main import build as old_build
from test_docx_visible_main import source, style
from test_docx_visible_word import blocked, build, original

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"


def paragraph(attributes="", *, marker="", properties=""):
    return (
        f'<w:p xmlns:w14="{W14}" {attributes}>{marker}'
        f"<w:r>{properties}<w:t>Требование😀</w:t></w:r></w:p>"
    )


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize(
    "attributes",
    [
        'w14:paraId="1234aBCD"',
        'w14:paraId="12345678" w14:textId="87654321" w:rsidR="1234ABCD"',
    ],
)
def test_paragraph_identities_keep_original_anchors_and_old_profile_closed(strict, attributes):
    raw, _ = source(paragraph(attributes), strict=strict)
    snapshot = build(raw)
    assert snapshot.complete and snapshot.analysis_text == "Требование😀"
    original(raw, snapshot)
    assert not old_build(raw).complete


@pytest.mark.parametrize(
    "attributes",
    [
        'w14:paraId=""',
        'w14:paraId="123"',
        'w14:textId="123456789"',
        'w14:paraId="ZZZZZZZZ"',
        'w14:unknown="12345678"',
        'w:paraId="12345678"',
        'w:rsidR="1234567Z"',
    ],
)
def test_unknown_or_malformed_identity_attributes_refuse(attributes):
    raw, _ = source(paragraph(attributes))
    blocked(raw)


def test_paragraph_id_attribute_does_not_authorize_it_on_a_run():
    raw, _ = source(
        f'<w:p xmlns:w14="{W14}"><w:r w14:paraId="12345678"><w:t>Text</w:t></w:r></w:p>'
    )
    blocked(raw)


@pytest.mark.parametrize("columns", [("0", "0"), ("0", "2")])
def test_column_bookmark_is_metadata_and_cannot_drop_text(columns):
    marker = (
        f'<w:bookmarkStart w:id="1" w:name="Columns" w:colFirst="{columns[0]}" '
        f'w:colLast="{columns[1]}"/><w:bookmarkEnd w:id="1"/>'
    )
    raw, _ = source(paragraph(marker=marker))
    snapshot = build(raw)
    assert snapshot.complete and snapshot.analysis_text == "Требование😀"
    original(raw, snapshot)


@pytest.mark.parametrize(
    "attributes",
    [
        'w:colFirst="0"',
        'w:colLast="0"',
        'w:colFirst="-1" w:colLast="0"',
        'w:colFirst="2" w:colLast="1"',
        'w:colFirst="0" w:colLast="2147483648"',
        'w:colFirst="NaN" w:colLast="0"',
        'w:colFirst="0" w:colLast="0" w:unknown="0"',
    ],
)
def test_malformed_column_bookmarks_refuse(attributes):
    marker = f'<w:bookmarkStart w:id="1" w:name="Columns" {attributes}/>'
    raw, _ = source(paragraph(marker=marker))
    blocked(raw)


@pytest.mark.parametrize("where", ["run", "style"])
@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_explicit_disabled_rtl_keeps_original_text_order(where, value):
    props = f'<w:rPr><w:rtl w:val="{value}"/></w:rPr>'
    styles = None
    if where == "style":
        styles = style("C", props, kind="character")
        props = '<w:rPr><w:rStyle w:val="C"/></w:rPr>'
    raw, _ = source(paragraph(properties=props), styles=styles)
    snapshot = build(raw)
    assert snapshot.complete and snapshot.analysis_text == "Требование😀"
    original(raw, snapshot)


@pytest.mark.parametrize(
    "property_xml",
    [
        "<w:rtl/>",
        '<w:rtl w:val="1"/>',
        '<w:rtl w:val="maybe"/>',
        '<w:rtl w:val="0" w:unknown="1"/>',
        '<w:rtl w:val="0"><w:t>Lost</w:t></w:rtl>',
    ],
)
def test_direction_support_remains_bounded(property_xml):
    raw, _ = source(paragraph(properties=f"<w:rPr>{property_xml}</w:rPr>"))
    blocked(raw)
