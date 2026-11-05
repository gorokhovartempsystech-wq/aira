"""Independent D02-02 positive acceptance: structure, exact text and source addresses."""

from hashlib import sha256
from importlib import import_module
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from docx_package_fixtures import STRICT_WORD_NS, WORD_NS
from docx_projection_fixtures import MAIN_PART, REL_ATTR_NS, package, paragraph

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"


def api():
    # The parent gate must collect even before the implementation exists.
    return import_module("ara.docx_package.projection")


def original_api():
    return import_module("ara.docx_package")


def anchor_tuple(anchor):
    return anchor.source_sha256, anchor.part_name, anchor.path


def assert_anchor(anchor, raw, main_xml, path, local_name, *, main_part=MAIN_PART, strict=False):
    assert isinstance(anchor, api().SourceAnchor)
    assert type(anchor.path) is tuple
    assert all(type(index) is int and index >= 0 for index in anchor.path)
    assert anchor_tuple(anchor) == (sha256(raw).hexdigest(), main_part, path)
    element = ET.fromstring(main_xml)
    for index in anchor.path:
        element = element[index]
    namespace = STRICT_WORD_NS if strict else WORD_NS
    assert element.tag == f"{{{namespace}}}{local_name}"
    return element


def assert_plain_paragraph(node, expected):
    assert node.kind == "paragraph"
    assert node.text == expected
    assert type(node.spans) is tuple
    assert node.has_opaque is False
    position = 0
    for span in node.spans:
        assert type(span.start) is int and type(span.end) is int
        assert span.start == position
        position += len(span.text)
        assert span.end == position
        assert span.reason is None
    assert node.text == "".join(span.text for span in node.spans)


def paragraph_nodes(blocks):
    for block in blocks:
        if block.kind == "paragraph":
            yield block
        elif block.kind == "table":
            for row in block.rows:
                for cell in row.cells:
                    yield from paragraph_nodes(cell.blocks)


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_project_nonstandard_main_part_with_both_word_namespaces_and_encodings(strict, encoding):
    main_part = "custom/Requirements.XML"
    expected = "  Датчик & <реле> 😀  "
    raw, main_xml = package(
        paragraph(expected), main_part=main_part, strict=strict, encoding=encoding
    )
    result = api().project_docx(raw)
    assert result.coverage_scope == "main-body-structural-v1"
    assert result.source.main_part == main_part
    assert type(result.blocks) is tuple
    assert type(result.notices) is tuple
    assert result.notices == ()
    assert result.has_unprojected_content is False
    assert len(result.blocks) == 1
    node = result.blocks[0]
    assert_plain_paragraph(node, expected)
    assert (node.properties_anchor, node.style_id, node.numbering_id, node.numbering_level) == (
        None,
        None,
        None,
        None,
    )
    assert_anchor(
        result.body_anchor, raw, main_xml, (0,), "body", main_part=main_part, strict=strict
    )
    assert_anchor(node.anchor, raw, main_xml, (0, 0), "p", main_part=main_part, strict=strict)
    span = node.spans[0]
    assert (span.kind, span.xml_space, span.break_type, span.hyperlink) == (
        "text",
        "preserve",
        None,
        None,
    )
    assert_anchor(span.anchor, raw, main_xml, (0, 0, 0, 0), "t", main_part=main_part, strict=strict)
    assert_anchor(
        span.run_anchor, raw, main_xml, (0, 0, 0), "r", main_part=main_part, strict=strict
    )
    assert original_api().export_original(result.source) == raw


def test_element_paths_count_properties_but_not_comments_and_distinguish_duplicate_text():
    first = """<w:p><w:pPr><w:pStyle w:val="LocalHeading"/>
      <w:numPr><w:ilvl w:val="3"/><w:numId w:val="0"/></w:numPr></w:pPr>
      <!-- p child comment --><?synthetic keep?>
      <w:r><w:rPr><w:b/></w:rPr><w:t>dupli</w:t><w:t>cate</w:t></w:r></w:p>"""
    body = first + "<!-- between --><?synthetic skip?>" + paragraph("duplicate")
    body += '<w:sectPr><w:pgSz w:w="11906"/></w:sectPr>'
    raw, main_xml = package(body, before_body='<w:background w:color="FFFFFF"/><!-- root -->')
    result = api().project_docx(raw)
    assert result.notices == ()
    assert_anchor(result.body_anchor, raw, main_xml, (1,), "body")
    left, right = result.blocks
    assert_plain_paragraph(left, "duplicate")
    assert_plain_paragraph(right, "duplicate")
    assert (left.style_id, left.numbering_id, left.numbering_level) == ("LocalHeading", "0", "3")
    assert_anchor(left.anchor, raw, main_xml, (1, 0), "p")
    assert_anchor(left.properties_anchor, raw, main_xml, (1, 0, 0), "pPr")
    assert_anchor(left.spans[0].run_anchor, raw, main_xml, (1, 0, 1), "r")
    assert_anchor(left.spans[0].anchor, raw, main_xml, (1, 0, 1, 1), "t")
    assert_anchor(left.spans[1].anchor, raw, main_xml, (1, 0, 1, 2), "t")
    assert_anchor(right.anchor, raw, main_xml, (1, 1), "p")
    assert left.anchor.path != right.anchor.path
    reopened = api().project_docx(raw)
    assert tuple(anchor_tuple(item.anchor) for item in reopened.blocks) == tuple(
        anchor_tuple(item.anchor) for item in result.blocks
    )
    assert tuple(anchor_tuple(span.anchor) for span in reopened.blocks[0].spans) == tuple(
        anchor_tuple(span.anchor) for span in left.spans
    )
    assert original_api().export_original(reopened.source) == raw


def test_runs_unicode_whitespace_tabs_breaks_and_empty_text_keep_exact_offsets():
    body = """<w:p><w:r><w:rPr><w:i/></w:rPr>
      <w:t xml:space="preserve">  A😀 &amp; &lt; </w:t><w:tab/>
      <w:t xml:space="default">B&#xD;C</w:t><w:br/><w:br w:type="page"/>
      <w:br w:type="column"/><w:cr/><w:t/></w:r>
      <w:r><w:t><![CDATA[ Z & < ]]></w:t></w:r></w:p>"""
    raw, main_xml = package(body)
    node = api().project_docx(raw).blocks[0]
    texts = ("  A😀 & < ", "\t", "B\rC", "\n", "\n", "\n", "\n", "", " Z & < ")
    assert_plain_paragraph(node, "".join(texts))
    assert tuple(span.text for span in node.spans) == texts
    assert tuple(span.kind for span in node.spans) == (
        "text",
        "tab",
        "text",
        "break",
        "break",
        "break",
        "break",
        "text",
        "text",
    )
    assert tuple(span.xml_space for span in node.spans) == (
        "preserve",
        None,
        "default",
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert tuple(span.break_type for span in node.spans) == (
        None,
        None,
        None,
        "textWrapping",
        "page",
        "column",
        "textWrapping",
        None,
        None,
    )
    for index, local_name in enumerate(("t", "tab", "t", "br", "br", "br", "cr", "t")):
        assert_anchor(node.spans[index].anchor, raw, main_xml, (0, 0, 0, index + 1), local_name)
        assert_anchor(node.spans[index].run_anchor, raw, main_xml, (0, 0, 0), "r")
    assert_anchor(node.spans[-1].run_anchor, raw, main_xml, (0, 0, 1), "r")
    assert_anchor(node.spans[-1].anchor, raw, main_xml, (0, 0, 1, 0), "t")
    # The emoji occupies one source-text position, not two JavaScript UTF-16 units.
    assert node.spans[0].end == 9
    assert node.spans[7].start == node.spans[7].end


def test_hyperlink_labels_and_bookmarks_keep_metadata_without_consuming_positions():
    body = """<w:p><w:bookmarkStart w:id="0" w:name="section"/>
      <w:r><w:t>Before </w:t></w:r>
      <w:hyperlink r:id="rExternal" w:anchor="section"><w:r><w:t>first</w:t></w:r>
        <w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t> link</w:t></w:r></w:hyperlink>
      <w:hyperlink w:anchor="section"><w:r><w:t> local</w:t></w:r></w:hyperlink>
      <w:bookmarkEnd w:id="0"/><w:r><w:t> after</w:t></w:r></w:p>"""
    raw, main_xml = package(
        body,
        links=[
            {
                "Id": "rExternal",
                "Type": REL_ATTR_NS + "/hyperlink",
                "Target": "https://example.invalid/synthetic#untouched",
                "TargetMode": "External",
            }
        ],
    )
    result = api().project_docx(raw)
    assert result.notices == ()
    node = result.blocks[0]
    assert_plain_paragraph(node, "Before first link local after")
    assert len(node.spans) == 5
    assert node.spans[0].hyperlink is None and node.spans[-1].hyperlink is None
    for span in node.spans[1:3]:
        link = span.hyperlink
        assert (link.relationship_id, link.bookmark) == ("rExternal", "section")
        assert_anchor(link.anchor, raw, main_xml, (0, 0, 2), "hyperlink")
    assert (node.spans[3].hyperlink.relationship_id, node.spans[3].hyperlink.bookmark) == (
        None,
        "section",
    )
    assert_anchor(node.spans[3].hyperlink.anchor, raw, main_xml, (0, 0, 3), "hyperlink")
    assert_anchor(node.spans[2].run_anchor, raw, main_xml, (0, 0, 2, 1), "r")
    assert_anchor(node.spans[2].anchor, raw, main_xml, (0, 0, 2, 1, 1), "t")


def table_body():
    return (
        paragraph("before")
        + """<w:tbl><w:tblPr><w:tblStyle w:val="SyntheticTable"/></w:tblPr>
        <w:tblGrid><w:gridCol w:w="1200"/><w:gridCol w:w="1200"/></w:tblGrid>
        <w:tr><w:trPr><w:cantSplit/></w:trPr>
          <w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/></w:tcPr>"""
        + paragraph("outer-before")
        + "<w:tbl><w:tr><w:tc>"
        + paragraph("nested")
        + "</w:tc></w:tr></w:tbl>"
        + paragraph("outer-after")
        + """</w:tc><w:tc><w:tcPr><w:vMerge/></w:tcPr><w:p/></w:tc></w:tr>
        <w:tr><w:tc/><w:tc><w:p/></w:tc></w:tr><w:tr/></w:tbl>"""
        + paragraph("after")
    )


def test_tables_preserve_body_order_nested_blocks_and_physical_merged_cells():
    raw, main_xml = package(table_body())
    result = api().project_docx(raw)
    assert result.notices == ()
    assert tuple(block.kind for block in result.blocks) == ("paragraph", "table", "paragraph")
    table = result.blocks[1]
    assert type(table.rows) is tuple and len(table.rows) == 3
    assert_anchor(table.anchor, raw, main_xml, (0, 1), "tbl")
    assert_anchor(table.properties_anchor, raw, main_xml, (0, 1, 0), "tblPr")
    first_row = table.rows[0]
    assert type(first_row.cells) is tuple and len(first_row.cells) == 2
    assert_anchor(first_row.anchor, raw, main_xml, (0, 1, 2), "tr")
    assert_anchor(first_row.properties_anchor, raw, main_xml, (0, 1, 2, 0), "trPr")
    left, right = first_row.cells
    assert type(left.blocks) is tuple and type(right.blocks) is tuple
    assert (left.grid_span, left.vertical_merge) == ("2", "restart")
    assert (right.grid_span, right.vertical_merge) == (None, "continue")
    assert tuple(item.kind for item in left.blocks) == ("paragraph", "table", "paragraph")
    assert_anchor(left.anchor, raw, main_xml, (0, 1, 2, 1), "tc")
    assert_anchor(left.properties_anchor, raw, main_xml, (0, 1, 2, 1, 0), "tcPr")
    nested = left.blocks[1]
    assert_anchor(nested.anchor, raw, main_xml, (0, 1, 2, 1, 2), "tbl")
    assert nested.properties_anchor is None
    assert nested.rows[0].properties_anchor is None
    assert nested.rows[0].cells[0].properties_anchor is None
    assert (nested.rows[0].cells[0].grid_span, nested.rows[0].cells[0].vertical_merge) == (
        None,
        None,
    )
    assert_plain_paragraph(right.blocks[0], "")
    assert table.rows[1].cells[0].blocks == ()
    assert table.rows[2].cells == ()
    assert [node.text for node in paragraph_nodes(result.blocks)] == [
        "before",
        "outer-before",
        "nested",
        "outer-after",
        "",
        "",
        "after",
    ]
    assert original_api().export_original(result.source) == raw


@pytest.mark.parametrize("body", ["", '<w:sectPr><w:pgSz w:w="11906"/></w:sectPr>'])
def test_empty_body_and_section_properties_have_no_text_blocks(body):
    raw, main_xml = package(body)
    result = api().project_docx(raw)
    assert result.blocks == ()
    assert result.notices == ()
    assert result.has_unprojected_content is False
    assert_anchor(result.body_anchor, raw, main_xml, (0,), "body")
    assert original_api().export_original(result.source) == raw


def test_empty_paragraph_and_empty_run_do_not_disappear_or_invent_text():
    raw, _ = package("<w:p/><w:p><w:r/></w:p><w:p><w:r><w:t/></w:r></w:p>")
    result = api().project_docx(raw)
    assert len(result.blocks) == 3
    for node in result.blocks:
        assert_plain_paragraph(node, "")
    assert result.blocks[0].spans == ()
    assert result.blocks[1].spans == ()
    span = result.blocks[2].spans[0]
    assert (span.kind, span.text, span.start, span.end) == ("text", "", 0, 0)
    assert result.notices == ()


def test_source_identity_changes_with_original_bytes_even_when_xml_paths_are_the_same():
    first, _ = package(paragraph("same"), comment=b"first synthetic snapshot")
    second, _ = package(paragraph("same"), comment=b"second synthetic snapshot")
    a, b = api().project_docx(first), api().project_docx(second)
    assert a.blocks[0].text == b.blocks[0].text == "same"
    assert a.blocks[0].anchor.path == b.blocks[0].anchor.path
    assert a.blocks[0].anchor.source_sha256 != b.blocks[0].anchor.source_sha256
    assert a.blocks[0].anchor.source_sha256 == sha256(first).hexdigest()
    assert b.blocks[0].anchor.source_sha256 == sha256(second).hexdigest()


def test_all_returned_structures_are_immutable_and_original_bytes_are_not_in_repr():
    marker = "SYNTHETIC_PROJECTION_ZIP_COMMENT_4738"
    body = (
        table_body()
        + '<w:p><w:hyperlink w:anchor="section"><w:r><w:t>x</w:t></w:r></w:hyperlink></w:p>'
    )
    raw, _ = package(body, comment=marker.encode())
    result = api().project_docx(raw)
    table = result.blocks[1]
    row = table.rows[0]
    cell = row.cells[0]
    node = cell.blocks[0]
    span = node.spans[0]
    link = result.blocks[-1].spans[0].hyperlink
    for target, field, replacement in (
        (result, "blocks", ()),
        (result, "source", None),
        (result, "coverage_scope", "changed"),
        (result.body_anchor, "path", (99,)),
        (node, "text", "changed"),
        (node, "spans", ()),
        (span, "text", "changed"),
        (span, "start", 99),
        (table, "rows", ()),
        (row, "cells", ()),
        (cell, "blocks", ()),
        (cell, "grid_span", "99"),
        (link, "bookmark", "changed"),
    ):
        before = getattr(target, field)
        with pytest.raises((AttributeError, TypeError)):
            setattr(target, field, replacement)
        assert getattr(target, field) == before
    assert marker not in repr(result)
    assert original_api().export_original(result.source) == raw


def test_existing_rendered_fixture_projects_body_and_keeps_unread_stories_explicit():
    raw = FIXTURE.read_bytes()
    result = api().project_docx(raw)
    assert (
        sha256(raw).hexdigest()
        == "73009626640400679d2b1a2031c565a964308073aa287067cf39088836176fcd"
    )
    assert len(result.source.entries) == 20
    assert result.coverage_scope == "main-body-structural-v1"
    nodes = list(paragraph_nodes(result.blocks))
    texts = [node.text for node in nodes]
    assert "Synthetic device requirements" in texts
    assert "Device classification" in texts
    assert "SYN-001" in texts
    assert "Desk light" in texts
    assert "D02-01 | SYNTHETIC CONTROL DOCUMENT" not in "\n".join(texts)
    assert any(block.kind == "table" for block in result.blocks)
    assert any(span.kind == "opaque" for node in nodes for span in node.spans)
    notices = {(notice.code, notice.part_name) for notice in result.notices}
    assert {
        ("unprojected_story", "word/header1.xml"),
        ("unprojected_story", "word/footer1.xml"),
        ("unprojected_part", "word/media/image1.png"),
    } <= notices
    assert not any(part in {"word/styles.xml", "word/numbering.xml"} for _, part in notices)
    assert result.has_unprojected_content is True
    assert original_api().export_original(result.source) == raw
    with ZipFile(BytesIO(raw)) as archive:
        main_xml = archive.read(result.source.main_part)
    for node in nodes:
        assert_anchor(node.anchor, raw, main_xml, node.anchor.path, "p")
