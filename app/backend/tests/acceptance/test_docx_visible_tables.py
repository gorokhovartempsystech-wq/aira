"""Literal visible table text, distinct cell flows and original-source highlights."""

from dataclasses import asdict, replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import group, resolve, run
from test_docx_table_catalog import cell, paragraph, row, source, table
from test_docx_visible_main import DOC, canonical, codes, payload, rehash, style
from test_docx_visible_main import source as styled_source

PROFILE = "docx-analysis/final-visible-tables-v1"


def api():
    return import_module("ara.docx_analysis.visible_tables")


def build(raw, **kwargs):
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    return api().build_table_snapshot(raw, **(identity | kwargs))


def request(f, start=0, end=None):
    end = len(f.text) if end is None else end
    return api().VisibleSpanRequest(f.fragment_id, start, end, f.text[start:end])


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_body_table_order_distinct_flows_and_exact_manifest(strict, encoding):
    body = (
        paragraph("Before")
        + table(row(cell(paragraph("A")) + cell(paragraph("B"))))
        + paragraph("After")
    )
    raw, xml = source(body, strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.analysis_text == "Before\n\nA\n\nB\n\nAfter"
    assert s.profile == PROFILE and s == build(raw)
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    assert [f.analysis_start for f in s.fragments] == [0, 8, 11, 14]
    assert [f.flow_anchor.path for f in s.fragments] == [(0,), (0, 1, 1, 0), (0, 1, 1, 1), (0,)]
    assert all(f.story_anchor.path == (0,) for f in s.fragments)
    f = s.fragments[1]
    assert (
        f.fragment_id
        == "vf-"
        + sha256(
            canonical(
                dict(
                    domain="docx-visible-fragment/1",
                    profile=PROFILE,
                    policy_version=s.policy_version,
                    source_sha256=s.source_sha256,
                    story_anchor=asdict(f.story_anchor),
                    flow_anchor=asdict(f.flow_anchor),
                    paragraph_anchor=asdict(f.paragraph_anchor),
                )
            )
        ).hexdigest()
    )
    result = api().map_table_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    assert [m.slices[0].anchor.path for m in result] == [
        (0, 0, 0, 0),
        (0, 1, 1, 0, 0, 0, 0),
        (0, 1, 1, 1, 0, 0, 0),
        (0, 2, 0, 0),
    ]
    root = ET.fromstring(xml)
    assert [resolve(root, m.slices[0].anchor).text for m in result] == ["Before", "A", "B", "After"]
    assert {
        ("metadata", "table_structure"),
        ("metadata", "table_grid"),
        ("metadata", "table_row"),
        ("metadata", "table_cell"),
    } <= codes(s)
    assert sha256(raw).hexdigest() == s.source_sha256


def test_identical_quotes_in_different_cells_keep_distinct_addresses():
    raw, _ = source(table(row(cell(paragraph("Same")) + cell(paragraph("Same")))))
    s = build(raw)
    a, b = s.fragments
    assert a.fragment_id != b.fragment_id and a.flow_anchor != b.flow_anchor
    result = api().map_table_spans(raw, s, requests=(request(b), request(a), request(b)))
    assert result[0] == result[2] and result[0].slices[0].anchor != result[1].slices[0].anchor
    assert result[0].slices[0].anchor.path == (0, 0, 1, 1, 0, 0, 0)


def test_nested_tables_and_multiple_paragraphs_preserve_cell_boundaries():
    nested = table(row(cell(paragraph("Nested"))), 1)
    outer = table(
        row(cell(paragraph("First") + nested + paragraph("Last")) + cell(paragraph("Other")))
    )
    raw, _ = source(outer)
    s = build(raw)
    assert s.complete and s.analysis_text == "First\n\nNested\n\nLast\n\nOther"
    assert [f.flow_anchor.path for f in s.fragments] == [
        (0, 0, 1, 0),
        (0, 0, 1, 0, 1, 1, 0),
        (0, 0, 1, 0),
        (0, 0, 1, 1),
    ]
    assert [f.paragraph_anchor.path for f in s.fragments] == [
        (0, 0, 1, 0, 0),
        (0, 0, 1, 0, 1, 1, 0, 0),
        (0, 0, 1, 0, 2),
        (0, 0, 1, 1, 0),
    ]


def test_horizontal_and_vertical_merges_do_not_duplicate_origin_text():
    span = '<w:gridSpan w:val="2"/>'
    rows = row(
        cell(paragraph("Origin"), span + '<w:vMerge w:val="restart"/>') + cell(paragraph("A"))
    )
    rows += row(cell("<w:p/>", span + "<w:vMerge/>") + cell(paragraph("B")))
    raw, _ = source(table(rows, 3))
    s = build(raw)
    assert s.complete and s.analysis_text == "Origin\n\nA\n\nB" and len(s.fragments) == 3
    assert ("excluded", "merged_cell_continuation") in codes(s)
    assert s.fragments[0].flow_anchor.path == (0, 0, 1, 0)
    assert s.fragments[2].flow_anchor.path == (0, 0, 2, 1)


@pytest.mark.parametrize(
    "blocks",
    [
        paragraph("Unexpected"),
        "<w:p><w:r><w:t> </w:t></w:r></w:p>",
        "<w:p><w:pPr/></w:p>",
        table(row(cell()), 1),
    ],
)
def test_noncanonical_continuation_content_is_not_silently_lost(blocks):
    rows = row(cell(properties='<w:vMerge w:val="restart"/>'), attrs="")
    rows += row(cell(blocks, "<w:vMerge/>"))
    s = build(source(table(rows, 1))[0])
    assert not s.complete and s.fragments == () and s.analysis_text == ""
    assert ("blocked", "unresolved_merged_cell_content") in codes(s)


def test_run_visibility_revisions_comments_unicode_and_gap_mapping_inside_cell():
    text = "<w:p>" + run("a") + "<w:r><w:rPr><w:vanish/></w:rPr><w:t>SECRET</w:t></w:r>"
    text += '<w:del w:id="1"><w:r><w:delText>old</w:delText></w:r></w:del>'
    text += '<w:ins w:id="2"><w:hyperlink w:anchor="X">' + run("😀é") + "</w:hyperlink></w:ins>"
    text += '<w:commentRangeStart w:id="3"/><w:commentRangeEnd w:id="3"/>'
    text += "<w:r><w:tab/><w:br/><w:t>Я</w:t></w:r></w:p>"
    raw, xml = source(table(row(cell(text)), 1))
    s = build(raw)
    assert s.complete and s.analysis_text == "a😀é\t\nЯ"
    (f,) = s.fragments
    result = api().map_table_spans(raw, s, requests=(request(f, 0, 4),))[0]
    assert [x.anchor.path for x in result.slices] == [
        (0, 0, 1, 0, 0, 0, 0),
        (0, 0, 1, 0, 0, 3, 0, 0, 0),
    ]
    root = ET.fromstring(xml)
    assert [resolve(root, x.anchor).text[x.start : x.end] for x in result.slices] == ["a", "😀é"]
    assert "SECRET" not in repr(s) + repr(f)
    assert {
        ("excluded", "hidden_run"),
        ("excluded", "deleted_content"),
        ("excluded", "comments_policy"),
    } <= codes(s)


def test_formatting_bidi_and_hidemark_keep_logical_text_order():
    rows = row(
        cell(
            paragraph("One"),
            '<w:hideMark/><w:tcW w:type="auto" w:w="0"/>'
            '<w:tcBorders><w:top w:val="single"/></w:tcBorders>',
        )
        + cell(paragraph("Two")),
        '<w:cantSplit/><w:tblHeader/><w:hidden w:val="0"/>',
    )
    props = (
        '<w:bidiVisual/><w:tblW w:type="auto" w:w="0"/>'
        '<w:tblBorders><w:insideH w:val="single"/></w:tblBorders>'
        '<w:tblCellMar><w:start w:w="40" w:type="dxa"/></w:tblCellMar>'
    )
    s = build(source(table(rows, 2, props))[0])
    assert s.complete and s.analysis_text == "One\n\nTwo"
    assert ("metadata", "table_properties") in codes(s)


@pytest.mark.parametrize(
    "body,styles,code",
    [
        (
            table(properties='<w:tblStyle w:val="T"/>'),
            style("T", kind="table"),
            "unresolved_table_style",
        ),
        (table(), style("T", kind="table", attrs='w:default="1"'), "implicit_table_style"),
        (table(row(properties="<w:hidden/>")), None, "unresolved_hidden_row"),
        (table(properties="<w:tblpPr/>"), None, "unsupported_table_properties"),
        (
            table(row(cell(properties='<w:cnfStyle w:val="100000000000"/>') + cell())),
            None,
            "unsupported_table_properties",
        ),
        (
            table(
                row(
                    cell(
                        '<w:p><w:pPr><w:rPr><w:del w:id="1"/></w:rPr></w:pPr>' + run("X") + "</w:p>"
                    )
                    + cell()
                )
            ),
            None,
            "unsupported_main_flow",
        ),
        (
            table(row(cell("<w:p>" + group() + group("To") + "</w:p>") + cell())),
            None,
            "move_catalog_blocked",
        ),
        ("<w:tbl>" + row() + "</w:tbl>", None, "table_catalog_blocked"),
    ],
)
def test_unsupported_style_structure_and_boundaries_never_partial(body, styles, code):
    raw, _ = styled_source(body, styles)
    s = build(raw)
    assert not s.complete and s.fragments == () and s.runs == () and s.paragraphs == ()
    assert ("blocked", code) in codes(s)


def test_unused_table_style_and_inherited_character_visibility():
    styles = style("T", "<w:unknown/>", "table") + style(
        "Hidden", "<w:rPr><w:vanish/></w:rPr>", "character"
    )
    text = (
        '<w:p><w:r><w:rPr><w:rStyle w:val="Hidden"/></w:rPr><w:t>SECRET</w:t></w:r>'
        + run("A")
        + "</w:p>"
    )
    raw, _ = styled_source(table(row(cell(text)), 1), styles)
    s = build(raw)
    assert s.complete and s.analysis_text == "A" and s.runs[0].visibility.hidden


def test_main_inline_moves_stay_supported_and_other_parts_stay_blocked():
    body = "<w:p>" + group(content=run("Old")) + group("To", content=run("New")) + "</w:p>"
    body += table(row(cell(paragraph("Cell"))), 1)
    raw, _ = source(body)
    assert build(raw).complete and build(raw).analysis_text == "New\n\nCell"
    raw, _ = source(
        body,
        extra_parts={"opaque.bin": b"synthetic"},
        extra_types={"opaque.bin": "application/octet-stream"},
    )
    s = build(raw)
    assert not s.complete and ("blocked", "unread_part") in codes(s)


def test_profiles_and_rehashed_foreign_flow_are_rejected():
    raw, _ = source(paragraph("A"))
    s = build(raw)
    old = import_module("ara.docx_analysis.visible_main")
    moved = import_module("ara.docx_analysis.visible_moves")
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    for builder, mapper in (
        (old.build_visible_snapshot, old.map_visible_spans),
        (moved.build_move_snapshot, moved.map_move_spans),
    ):
        previous = builder(raw, **identity)
        assert previous.fragments[0].fragment_id != s.fragments[0].fragment_id
        error("invalid_snapshot", lambda: mapper(raw, s, requests=()))
        error("invalid_snapshot", lambda: api().map_table_spans(raw, previous, requests=()))
    raw, _ = source(table(row(cell(paragraph("Same")) + cell(paragraph("Same")))))
    s = build(raw)
    a, b = s.fragments
    fake = rehash(replace(s, fragments=(replace(a, flow_anchor=b.flow_anchor), b)))
    error("invalid_snapshot", lambda: api().map_table_spans(raw, fake, requests=()))
