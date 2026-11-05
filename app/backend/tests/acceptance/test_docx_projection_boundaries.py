"""Independent D02-02 boundaries: explicit coverage, limits and inert operations."""

import base64
import json
import subprocess
import sys
import traceback
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from docx_package_fixtures import (
    MAIN_CONTENT_TYPE,
    RELS_CONTENT_TYPE,
    WORD_NS,
    build_package,
    content_types_xml,
    minimal_parts,
    relationships_xml,
)

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "SYNTHETIC_UNPROJECTED_CONTENT_9371"
OTHER_NS = "urn:synthetic:projection-boundary"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAIN = "word/document.xml"
WORD_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
AUXILIARY_TYPES = (
    WORD_TYPE + "styles+xml",
    WORD_TYPE + "numbering+xml",
    WORD_TYPE + "settings+xml",
    WORD_TYPE + "webSettings+xml",
    WORD_TYPE + "fontTable+xml",
    "application/vnd.openxmlformats-officedocument.theme+xml",
    "application/vnd.openxmlformats-package.core-properties+xml",
    "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    "application/vnd.openxmlformats-officedocument.custom-properties+xml",
)


def api():
    return import_module("ara.docx_package.projection")


def package_api():
    return import_module("ara.docx_package")


def w(local):
    return f"{{{WORD_NS}}}{local}"


def element(local, parent=None, **attributes):
    if parent is None:
        return ET.Element(w(local), {w(key): value for key, value in attributes.items()})
    return ET.SubElement(parent, w(local), {w(key): value for key, value in attributes.items()})


def text_run(parent, text):
    run = element("r", parent)
    element("t", run).text = text
    return run


def document():
    root = element("document")
    body = element("body", root)
    return root, body


def paragraph(parent, text="Visible text"):
    value = element("p", parent)
    text_run(value, text)
    return value


def raw_package(root, *, extra=None, types=None, comment=b""):
    parts = minimal_parts()
    parts[MAIN] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    parts.update(extra or {})
    parts["[Content_Types].xml"] = content_types_xml(
        defaults={
            "rels": RELS_CONTENT_TYPE,
            "xml": "application/xml",
            "bin": "application/octet-stream",
        },
        overrides={"/" + MAIN: MAIN_CONTENT_TYPE, **(types or {})},
    )
    return build_package(parts, comment=comment)


def plain_package():
    root, body = document()
    paragraph(body)
    return raw_package(root)


def notices(projection):
    return tuple(
        (item.code, item.part_name, None if item.anchor is None else item.anchor.path)
        for item in projection.notices
    )


def assert_anchor(anchor, path, projection):
    assert isinstance(anchor, api().SourceAnchor)
    assert type(anchor.path) is tuple
    assert anchor.path == path
    assert anchor.part_name == MAIN
    assert anchor.source_sha256 == projection.source.sha256


def assert_original(projection, data):
    assert package_api().export_original(projection.source) == data
    assert projection.has_unprojected_content is bool(projection.notices)
    assert projection.coverage_scope == "main-body-structural-v1"


def reject(operation, exception_type, code):
    with pytest.raises(exception_type) as caught:
        operation()
    error = caught.value
    assert error.code == code
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    assert PRIVATE not in str(error) + repr(error)
    assert PRIVATE not in "".join(traceback.format_exception(error))
    return error.message


def test_foreign_projection_limits_are_rejected_without_coercion():
    module = api()
    for value in ({}, 1, True, PRIVATE, object(), package_api().DocxLimits()):
        reject(
            lambda: module.project_docx(plain_package(), projection_limits=value),
            module.ProjectionError,
            "invalid_input",
        )


@pytest.mark.parametrize("field", ["max_nodes", "max_depth"])
def test_projection_limit_fields_are_strict_positive_integers(field):
    module = api()
    for value in (0, -1, True, 1.0, "1", None):
        reject(
            lambda: module.project_docx(
                plain_package(), projection_limits=module.ProjectionLimits(**{field: value})
            ),
            module.ProjectionError,
            "invalid_input",
        )


def test_projection_limits_defaults_are_exact_and_immutable():
    limits = api().ProjectionLimits()
    for name, expected in (("max_nodes", 100000), ("max_depth", 128)):
        assert type(getattr(limits, name)) is int
        assert getattr(limits, name) == expected
        with pytest.raises((AttributeError, TypeError)):
            setattr(limits, name, expected + 1)


def test_input_and_package_failures_retain_docx_error_codes():
    module = api()
    base = package_api()
    for value in (None, PRIVATE, Path(PRIVATE), bytearray(plain_package()), memoryview(b"bad")):
        reject(lambda: module.project_docx(value), base.DocxError, "invalid_input")
    invalid_messages = {
        reject(lambda: module.project_docx(value), base.DocxError, "invalid_package")
        for value in (b"", PRIVATE.encode(), b"PK\x03\x04" + PRIVATE.encode())
    }
    assert len(invalid_messages) == 1
    reject(
        lambda: module.project_docx(plain_package(), limits={}),
        base.DocxError,
        "invalid_input",
    )
    reject(
        lambda: module.project_docx(plain_package(), limits=base.DocxLimits(max_archive_bytes=1)),
        base.DocxError,
        "package_limit_exceeded",
    )


@pytest.mark.parametrize("field", ["max_nodes", "max_depth"])
def test_projection_limits_count_properties_and_opaque_subtrees_inclusively(field):
    module = api()
    root, body = document()
    para = paragraph(body)
    properties = element("pPr", para)
    current = ET.SubElement(properties, f"{{{OTHER_NS}}}property")
    for _ in range(5):
        current = ET.SubElement(current, f"{{{OTHER_NS}}}nested")
    opaque = ET.SubElement(body, f"{{{OTHER_NS}}}wrapper")
    for _ in range(3):
        opaque = ET.SubElement(opaque, f"{{{OTHER_NS}}}hidden")
    opaque.text = PRIVATE
    stack = [(root, 1)]
    count = depth = 0
    while stack:
        node, level = stack.pop()
        count += 1
        depth = max(depth, level)
        stack.extend((child, level + 1) for child in node)
    exact = count if field == "max_nodes" else depth
    raw = raw_package(root)
    result = module.project_docx(raw, projection_limits=module.ProjectionLimits(**{field: exact}))
    assert_original(result, raw)
    reject(
        lambda: module.project_docx(
            raw, projection_limits=module.ProjectionLimits(**{field: exact - 1})
        ),
        module.ProjectionError,
        "projection_limit_exceeded",
    )


def test_deep_unknown_content_hits_projection_limit_not_python_recursion():
    module = api()
    parts = minimal_parts()
    parts[MAIN] = (
        f'<w:document xmlns:w="{WORD_NS}" xmlns:s="{OTHER_NS}"><w:body>'
        + "<s:unknown>" * 1800
        + PRIVATE
        + "</s:unknown>" * 1800
        + "</w:body></w:document>"
    ).encode()
    reject(
        lambda: module.project_docx(
            build_package(parts), projection_limits=module.ProjectionLimits(max_depth=16)
        ),
        module.ProjectionError,
        "projection_limit_exceeded",
    )


def test_deep_opaque_content_with_explicitly_sufficient_limits_is_supported():
    module = api()
    parts = minimal_parts()
    parts[MAIN] = (
        f'<w:document xmlns:w="{WORD_NS}" xmlns:s="{OTHER_NS}"><w:body>'
        + "<s:unknown>" * 1800
        + PRIVATE
        + "</s:unknown>" * 1800
        + "</w:body></w:document>"
    ).encode()
    raw = build_package(parts)
    result = module.project_docx(
        raw, projection_limits=module.ProjectionLimits(max_depth=2000, max_nodes=2000)
    )
    assert len(result.blocks) == 1 and result.blocks[0].kind == "opaque"
    assert notices(result) == (("unsupported_element", MAIN, (0, 0)),)
    assert_original(result, raw)


def test_deep_supported_tables_obey_explicit_limits_without_recursive_walk_failure():
    module = api()
    levels = 400
    parts = minimal_parts()
    parts[MAIN] = (
        f'<w:document xmlns:w="{WORD_NS}"><w:body>'
        + "<w:tbl><w:tr><w:tc>" * levels
        + "<w:p><w:r><w:t>Deep text</w:t></w:r></w:p>"
        + "</w:tc></w:tr></w:tbl>" * levels
        + "</w:body></w:document>"
    ).encode()
    raw = build_package(parts)
    result = module.project_docx(
        raw, projection_limits=module.ProjectionLimits(max_depth=2000, max_nodes=2000)
    )
    blocks = result.blocks
    for _ in range(levels):
        assert len(blocks) == 1 and blocks[0].kind == "table"
        assert len(blocks[0].rows) == len(blocks[0].rows[0].cells) == 1
        blocks = blocks[0].rows[0].cells[0].blocks
    assert len(blocks) == 1 and blocks[0].kind == "paragraph"
    assert blocks[0].text == "Deep text"
    assert len(blocks[0].anchor.path) == 3 * levels + 2
    assert result.notices == ()
    assert_original(result, raw)


@pytest.mark.parametrize("position", ["paragraph", "run", "hyperlink"])
def test_unknown_inline_subtree_is_one_opaque_span_and_never_joins_text(position):
    root, body = document()
    para = element("p", body)
    text_run(para, "L")
    if position == "run":
        container = element("r", para)
    elif position == "hyperlink":
        container = element("hyperlink", para, anchor="synthetic-bookmark")
    else:
        container = para
    unknown = ET.SubElement(container, f"{{{OTHER_NS}}}wrapper")
    text_run(unknown, PRIVATE)
    text_run(para, "R")
    raw = raw_package(root)
    result = api().project_docx(raw)
    block = result.blocks[0]
    assert block.kind == "paragraph"
    assert block.text == "L\ufffcR"
    assert block.has_opaque is True
    assert tuple(span.kind for span in block.spans) == ("text", "opaque", "text")
    assert tuple((span.start, span.end) for span in block.spans) == ((0, 1), (1, 2), (2, 3))
    opaque = block.spans[1]
    path = (0, 0, 1, 0) if position != "paragraph" else (0, 0, 1)
    assert_anchor(opaque.anchor, path, result)
    if position == "run":
        assert_anchor(opaque.run_anchor, (0, 0, 1), result)
    else:
        assert opaque.run_anchor is None
    assert opaque.reason == "unsupported_element"
    assert opaque.xml_space is None and opaque.break_type is None
    assert notices(result) == (("unsupported_element", MAIN, path),)
    assert PRIVATE not in repr(block) + repr(result.notices)
    assert_original(result, raw)


@pytest.mark.parametrize(
    "local", ["drawing", "object", "sdt", "customXml", "smartTag", "fldSimple"]
)
def test_known_complex_inline_elements_are_explicitly_opaque(local):
    root, body = document()
    para = element("p", body)
    complex_element = element(local, para)
    text_run(complex_element, PRIVATE)
    raw = raw_package(root)
    result = api().project_docx(raw)
    block = result.blocks[0]
    assert block.kind == "paragraph" and block.text == "\ufffc"
    assert len(block.spans) == 1 and block.spans[0].kind == "opaque"
    assert notices(result) == (("unsupported_element", MAIN, (0, 0, 0)),)
    assert PRIVATE not in repr(block)
    assert_original(result, raw)


def test_alternate_content_does_not_concatenate_mutually_exclusive_branches():
    root, body = document()
    para = element("p", body)
    alternative = ET.SubElement(para, f"{{{MC_NS}}}AlternateContent")
    for name in ("Choice", "Fallback"):
        branch = ET.SubElement(alternative, f"{{{MC_NS}}}{name}")
        text_run(branch, PRIVATE + name)
    result = api().project_docx(raw_package(root))
    assert result.blocks[0].text == "\ufffc"
    assert len(result.blocks[0].spans) == 1
    assert len(result.notices) == 1
    assert PRIVATE not in repr(result.blocks)


@pytest.mark.parametrize("local", ["t", "tab", "br", "cr"])
def test_known_inline_leaf_with_children_is_opaque_instead_of_partially_read(local):
    root, body = document()
    para = element("p", body)
    text_run(para, "L")
    run = element("r", para)
    leaf = element(local, run)
    leaf.text = PRIVATE
    child = ET.SubElement(leaf, f"{{{OTHER_NS}}}child")
    child.text = PRIVATE
    child.tail = PRIVATE
    text_run(para, "R")
    raw = raw_package(root)
    result = api().project_docx(raw)
    block = result.blocks[0]
    assert block.kind == "paragraph" and block.text == "L\ufffcR"
    assert block.spans[1].kind == "opaque"
    assert block.spans[1].reason == "unsupported_structure"
    assert notices(result) == (("unsupported_structure", MAIN, (0, 0, 1, 0)),)
    assert PRIVATE not in repr(block)
    assert_original(result, raw)


def test_comments_and_note_references_are_not_silently_discarded():
    root, body = document()
    para = element("p", body)
    names = ("commentRangeStart", "commentRangeEnd", "commentReference", "footnoteReference")
    for name in names:
        element(name, para, id="7")
    run = element("r", para)
    element("endnoteReference", run, id="8")
    result = api().project_docx(raw_package(root))
    block = result.blocks[0]
    assert block.text == "\ufffc" * 5
    assert len(block.spans) == len(result.notices) == 5
    assert all(span.kind == "opaque" for span in block.spans)
    assert all(notice.code == "unsupported_element" for notice in result.notices)


def test_bookmarks_and_section_properties_do_not_create_false_coverage_notices():
    root, body = document()
    para = element("p", body)
    element("bookmarkStart", para, id="1", name="synthetic")
    text_run(para, "Visible")
    element("bookmarkEnd", para, id="1")
    element("sectPr", body)
    result = api().project_docx(raw_package(root))
    assert len(result.blocks) == 1
    assert result.blocks[0].text == "Visible"
    assert len(result.blocks[0].spans) == 1
    assert not result.blocks[0].has_opaque
    assert result.notices == () and result.has_unprojected_content is False


def test_unknown_body_wrapper_is_one_block_and_not_recursively_unwrapped():
    root, body = document()
    wrapper = ET.SubElement(body, f"{{{OTHER_NS}}}wrapper")
    paragraph(wrapper, PRIVATE)
    table = element("tbl", wrapper)
    paragraph(element("tc", element("tr", table)), PRIVATE)
    raw = raw_package(root)
    result = api().project_docx(raw)
    assert len(result.blocks) == 1
    opaque = result.blocks[0]
    assert opaque.kind == "opaque" and opaque.reason == "unsupported_element"
    assert opaque.element_name == f"{{{OTHER_NS}}}wrapper"
    assert_anchor(opaque.anchor, (0, 0), result)
    assert getattr(opaque, "text", None) is None
    assert notices(result) == (("unsupported_element", MAIN, (0, 0)),)
    assert PRIVATE not in repr(result.blocks)
    assert_original(result, raw)


@pytest.mark.parametrize("position", ["table", "row"])
def test_unknown_table_or_row_structure_preserves_one_whole_opaque_table(position):
    root, body = document()
    table = element("tbl", body)
    row = element("tr", table)
    paragraph(element("tc", row), PRIVATE)
    ET.SubElement(table if position == "table" else row, f"{{{OTHER_NS}}}extension")
    paragraph(body, "After table")
    raw = raw_package(root)
    result = api().project_docx(raw)
    assert tuple(block.kind for block in result.blocks) == ("opaque", "paragraph")
    opaque = result.blocks[0]
    assert opaque.reason == "unsupported_structure" and opaque.element_name == w("tbl")
    assert_anchor(opaque.anchor, (0, 0), result)
    assert result.blocks[1].text == "After table"
    assert notices(result) == (("unsupported_structure", MAIN, (0, 0)),)
    assert PRIVATE not in repr(opaque)
    assert_original(result, raw)


def test_unknown_cell_block_does_not_discard_the_known_table_structure():
    root, body = document()
    cell = element("tc", element("tr", element("tbl", body)))
    paragraph(cell, "Before")
    wrapper = ET.SubElement(cell, f"{{{OTHER_NS}}}wrapper")
    paragraph(wrapper, PRIVATE)
    paragraph(cell, "After")
    result = api().project_docx(raw_package(root))
    table = result.blocks[0]
    assert table.kind == "table"
    blocks = table.rows[0].cells[0].blocks
    assert tuple(block.kind for block in blocks) == ("paragraph", "opaque", "paragraph")
    assert (blocks[0].text, blocks[2].text) == ("Before", "After")
    assert notices(result) == (("unsupported_element", MAIN, (0, 0, 0, 0, 1)),)


@pytest.mark.parametrize("property_name", ["pPr", "pStyle", "numPr", "numId", "ilvl", "rPr"])
def test_duplicate_singleton_paragraph_properties_do_not_choose_a_winner(property_name):
    root, body = document()
    para = paragraph(body, PRIVATE)
    props = element("pPr", para)
    if property_name == "pPr":
        element("pPr", para)
    else:
        if property_name == "rPr":
            parent = para[0]
        elif property_name in {"numId", "ilvl"}:
            parent = element("numPr", props)
        else:
            parent = props
        for value in ("first", "second"):
            element(property_name, parent, val=value)
    raw = raw_package(root)
    result = api().project_docx(raw)
    assert len(result.blocks) == 1
    assert result.blocks[0].kind == "opaque"
    assert result.blocks[0].reason == "unsupported_structure"
    assert result.blocks[0].element_name == w("p")
    assert notices(result) == (("unsupported_structure", MAIN, (0, 0)),)
    assert PRIVATE not in repr(result.blocks)
    assert_original(result, raw)


@pytest.mark.parametrize(
    "property_name", ["tblPr", "tblGrid", "trPr", "tcPr", "gridSpan", "vMerge"]
)
def test_duplicate_singleton_table_properties_do_not_choose_a_winner(property_name):
    root, body = document()
    table = element("tbl", body)
    row = element("tr", table)
    cell = element("tc", row)
    paragraph(cell, PRIVATE)
    if property_name in {"tblPr", "tblGrid"}:
        parent = table
    elif property_name == "trPr":
        parent = row
    elif property_name == "tcPr":
        parent = cell
    else:
        parent = element("tcPr", cell)
    for value in ("1", "2"):
        element(property_name, parent, val=value)
    raw = raw_package(root)
    result = api().project_docx(raw)
    assert len(result.blocks) == 1 and result.blocks[0].kind == "opaque"
    assert result.blocks[0].reason == "unsupported_structure"
    assert result.blocks[0].element_name == w("tbl")
    assert notices(result) == (("unsupported_structure", MAIN, (0, 0)),)
    assert_original(result, raw)


def test_duplicate_properties_in_nested_table_do_not_hide_outer_table():
    root, body = document()
    outer = element("tbl", body)
    cell = element("tc", element("tr", outer))
    paragraph(cell, "Before nested")
    nested = element("tbl", cell)
    element("tblPr", nested)
    element("tblPr", nested)
    paragraph(cell, "After nested")
    result = api().project_docx(raw_package(root))
    table = result.blocks[0]
    assert table.kind == "table"
    blocks = table.rows[0].cells[0].blocks
    assert tuple(item.kind for item in blocks) == ("paragraph", "opaque", "paragraph")
    assert blocks[1].reason == "unsupported_structure"
    assert notices(result) == (("unsupported_structure", MAIN, (0, 0, 0, 0, 1)),)


@pytest.mark.parametrize(
    "local",
    [
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "rPrChange",
        "pPrChange",
        "tblGridChange",
        "numberingChange",
        "cellIns",
        "cellDel",
        "cellMerge",
        "moveFromRangeStart",
        "moveToRangeEnd",
    ],
)
def test_paragraph_revisions_never_become_an_implicitly_accepted_version(local):
    root, body = document()
    para = paragraph(body, "Before revision")
    revision = element(local, para)
    text_run(revision, PRIVATE)
    paragraph(body, "After paragraph")
    raw = raw_package(root)
    result = api().project_docx(raw)
    opaque, after = result.blocks
    assert opaque.kind == "opaque" and opaque.reason == "tracked_change"
    assert opaque.element_name == w("p")
    assert_anchor(opaque.anchor, (0, 0), result)
    assert after.text == "After paragraph"
    assert notices(result) == (("tracked_change", MAIN, (0, 0)),)
    assert PRIVATE not in repr(result.blocks)
    assert_original(result, raw)


@pytest.mark.parametrize("properties", ["pPr", "rPr"])
def test_revision_inside_paragraph_properties_blocks_the_paragraph(properties):
    root, body = document()
    para = paragraph(body)
    parent = para if properties == "pPr" else para[0]
    props = element(properties, parent)
    element(properties + "Change", props)
    result = api().project_docx(raw_package(root))
    assert result.blocks[0].kind == "opaque"
    assert result.blocks[0].reason == "tracked_change"
    assert notices(result) == (("tracked_change", MAIN, (0, 0)),)


@pytest.mark.parametrize("properties", ["tblPr", "tblGrid", "trPr", "tcPr"])
def test_revision_in_table_row_or_cell_properties_blocks_the_table(properties):
    root, body = document()
    table = element("tbl", body)
    row = element("tr", table)
    cell = element("tc", row)
    paragraph(cell, PRIVATE)
    parent = {"tblPr": table, "tblGrid": table, "trPr": row, "tcPr": cell}[properties]
    props = element(properties, parent)
    element(properties + "Change", props)
    raw = raw_package(root)
    result = api().project_docx(raw)
    assert len(result.blocks) == 1 and result.blocks[0].kind == "opaque"
    assert result.blocks[0].reason == "tracked_change"
    assert result.blocks[0].element_name == w("tbl")
    assert notices(result) == (("tracked_change", MAIN, (0, 0)),)
    assert_original(result, raw)


def test_revision_in_cell_paragraph_does_not_hide_unaffected_cells():
    root, body = document()
    table = element("tbl", body)
    row = element("tr", table)
    first = paragraph(element("tc", row))
    element("ins", first)
    paragraph(element("tc", row), "Unaffected cell")
    result = api().project_docx(raw_package(root))
    table = result.blocks[0]
    assert table.kind == "table" and len(table.rows[0].cells) == 2
    assert table.rows[0].cells[0].blocks[0].reason == "tracked_change"
    assert table.rows[0].cells[1].blocks[0].text == "Unaffected cell"
    assert notices(result) == (("tracked_change", MAIN, (0, 0, 0, 0, 0)),)


@pytest.mark.parametrize("include_field", [False, True])
def test_reason_priority_is_field_then_revision_then_unsupported_structure(include_field):
    root, body = document()
    para = paragraph(body, PRIVATE)
    element("pPr", para)
    element("pPr", para)
    element("ins", para)
    if include_field:
        element("fldChar", para)
    result = api().project_docx(raw_package(root))
    assert len(result.blocks) == 1 and result.blocks[0].kind == "opaque"
    reason = "complex_field" if include_field else "tracked_change"
    path = (0,) if include_field else (0, 0)
    assert result.blocks[0].reason == reason
    assert notices(result) == ((reason, MAIN, path),)


@pytest.mark.parametrize("local", ["fldChar", "instrText"])
@pytest.mark.parametrize("location", ["run", "unknown_wrapper", "properties"])
def test_complex_field_anywhere_inside_body_makes_body_explicitly_opaque(local, location):
    root, body = document()
    para = paragraph(body, "Visible prefix")
    if location == "run":
        parent = para[0]
    elif location == "properties":
        parent = element("pPr", para)
    else:
        parent = ET.SubElement(body, f"{{{OTHER_NS}}}wrapper")
    field = element(local, parent)
    field.text = PRIVATE
    paragraph(body, "Visible suffix")
    raw = raw_package(root)
    result = api().project_docx(raw)
    assert len(result.blocks) == 1
    opaque = result.blocks[0]
    assert opaque.kind == "opaque" and opaque.reason == "complex_field"
    assert opaque.element_name == w("body")
    assert_anchor(opaque.anchor, (0,), result)
    assert notices(result) == (("complex_field", MAIN, (0,)),)
    assert PRIVATE not in repr(result.blocks)
    assert_original(result, raw)


def test_complex_field_across_paragraphs_does_not_expose_cached_result_as_plain_text():
    root, body = document()
    first = paragraph(body, "Prefix")
    element("fldChar", element("r", first), fldCharType="begin")
    element("instrText", element("r", first)).text = PRIVATE
    middle = paragraph(body, "Cached field result")
    element("fldChar", element("r", middle), fldCharType="separate")
    last = paragraph(body, "Suffix")
    element("fldChar", element("r", last), fldCharType="end")
    result = api().project_docx(raw_package(root))
    assert len(result.blocks) == 1 and result.blocks[0].reason == "complex_field"
    assert getattr(result.blocks[0], "text", None) is None
    assert notices(result) == (("complex_field", MAIN, (0,)),)


def test_opaque_body_still_obeys_projection_node_limit():
    module = api()
    root, body = document()
    paragraph(body)
    element("fldChar", body)
    hidden = ET.SubElement(body, f"{{{OTHER_NS}}}wrapper")
    for _ in range(100):
        ET.SubElement(hidden, f"{{{OTHER_NS}}}child")
    reject(
        lambda: module.project_docx(
            raw_package(root), projection_limits=module.ProjectionLimits(max_nodes=10)
        ),
        module.ProjectionError,
        "projection_limit_exceeded",
    )


def test_other_story_fields_are_not_mixed_into_main_body():
    root, body = document()
    paragraph(body, "Main text")
    header = element("hdr")
    para = paragraph(header, PRIVATE)
    element("fldChar", element("r", para), fldCharType="begin")
    path = "custom/a-header.xml"
    raw = raw_package(
        root,
        extra={path: ET.tostring(header)},
        types={"/" + path: WORD_TYPE + "header+xml"},
    )
    result = api().project_docx(raw)
    assert result.blocks[0].kind == "paragraph" and result.blocks[0].text == "Main text"
    assert notices(result) == (("unprojected_story", path, None),)
    assert_original(result, raw)


def test_auxiliary_parts_are_not_reported_as_missing_user_text():
    root, body = document()
    paragraph(body)
    extra = {f"custom/aux-{index}.xml": b"<aux/>" for index in range(len(AUXILIARY_TYPES))}
    types = {"/" + name: kind for name, kind in zip(extra, AUXILIARY_TYPES, strict=True)}
    raw = raw_package(root, extra=extra, types=types)
    result = api().project_docx(raw)
    assert result.notices == () and result.has_unprojected_content is False
    assert_original(result, raw)


def test_story_and_unknown_part_notices_use_content_types_and_actual_names():
    root, body = document()
    paragraph(body)
    stories = ("header", "footer", "footnotes", "endnotes", "comments", "document.glossary")
    extra = {f"custom/story-{index}.xml": b"<story/>" for index in range(len(stories))}
    types = {
        "/" + name: WORD_TYPE + story + "+xml" for name, story in zip(extra, stories, strict=True)
    }
    extra["word/header1.xml"] = b"<unknown/>"
    extra["assets/opaque.bin"] = PRIVATE.encode()
    raw = raw_package(root, extra=extra, types=types)
    result = api().project_docx(raw)
    expected = tuple(
        (
            "unprojected_story" if path.startswith("custom/story-") else "unprojected_part",
            path,
            None,
        )
        for path in sorted(extra)
    )
    assert notices(result) == expected
    assert PRIVATE not in repr(result.notices)
    assert_original(result, raw)


def test_main_notices_follow_xml_order_then_other_parts_and_do_not_duplicate_descendants():
    root = element("document")
    outer = ET.SubElement(root, f"{{{OTHER_NS}}}before")
    ET.SubElement(outer, f"{{{OTHER_NS}}}nested").text = PRIVATE
    body = element("body", root)
    para = element("p", body)
    ET.SubElement(para, f"{{{OTHER_NS}}}inline")
    ET.SubElement(root, f"{{{OTHER_NS}}}after")
    element("background", root)
    raw = raw_package(root, extra={"z-last.bin": b"z", "a-first.bin": b"a"})
    result = api().project_docx(raw)
    assert notices(result) == (
        ("unprojected_root_element", MAIN, (0,)),
        ("unsupported_element", MAIN, (1, 0, 0)),
        ("unprojected_root_element", MAIN, (2,)),
        ("unprojected_part", "a-first.bin", None),
        ("unprojected_part", "z-last.bin", None),
    )
    assert len(set(notices(result))) == len(result.notices)
    assert PRIVATE not in repr(result.notices)
    assert_original(result, raw)


@pytest.mark.parametrize("comment", [b"metadata PK\x05\x06", b"PK\x05\x06" + b"\0" * 22])
def test_valid_zip_signature_in_archive_comment_does_not_break_projection(comment):
    root, body = document()
    paragraph(body, "Comment-safe")
    raw = raw_package(root, comment=comment)
    result = api().project_docx(raw)
    assert result.blocks[0].text == "Comment-safe"
    assert_original(result, raw)


def test_projection_import_and_operations_have_no_external_io_or_logging():
    root, body = document()
    para = paragraph(body, "Visible ")
    link = element("hyperlink", para)
    link.set(f"{{{R_NS}}}id", "rExternal")
    text_run(link, "link")
    raw = raw_package(
        root,
        extra={
            "word/_rels/document.xml.rels": relationships_xml(
                [
                    {
                        "Id": "rExternal",
                        "Type": R_NS + "/hyperlink",
                        "Target": "https://example.invalid/synthetic-external",
                        "TargetMode": "External",
                    }
                ]
            )
        },
    )
    code = """
import base64, builtins, importlib, io, json, logging, os, socket, subprocess, tempfile
from pathlib import Path
import urllib.request, zipfile, dataclasses, hashlib
from xml.etree import ElementTree
import xml.parsers.expat
import psycopg, sqlalchemy
import ara.config, ara.db
data = base64.b64decode(PAYLOAD)
names = ['ara.docx_package.projection'] + [
    '.'.join(p.with_suffix('').parts[1:])
    for p in sorted(Path('src/ara/docx_package/projection').rglob('*.py'))
    if p.name != '__init__.py'
]
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external I/O or logging in projection')
for target, name in (
    (builtins, 'open'), (io, 'open'), (Path, 'open'), (Path, 'read_text'), (Path, 'read_bytes'),
    (Path, 'write_text'), (Path, 'write_bytes'), (Path, 'mkdir'), (os, 'open'), (os, 'mkdir'),
    (os, 'system'), (os, 'popen'), (socket, 'socket'), (socket, 'create_connection'),
    (subprocess, 'Popen'), (subprocess, 'run'), (urllib.request, 'urlopen'),
    (tempfile, 'TemporaryFile'), (tempfile, 'NamedTemporaryFile'), (tempfile, 'mkdtemp'),
    (psycopg, 'connect'), (sqlalchemy, 'create_engine'), (ara.config, 'load_settings'),
    (ara.db, 'create_database_engine'), (logging.Logger, '_log'),
):
    setattr(target, name, forbidden)
for name in names:
    importlib.import_module(name)
api = importlib.import_module('ara.docx_package.projection')
package = importlib.import_module('ara.docx_package')
projection = api.project_docx(data)
assert projection.blocks[0].text == 'Visible link'
assert package.export_original(projection.source) == data
assert repr(data) not in repr(projection)
try:
    api.project_docx(MARKER.encode())
except package.DocxError as error:
    assert error.code == 'invalid_package'
    assert MARKER not in str(error)
else:
    raise AssertionError('Invalid package unexpectedly accepted')
try:
    api.project_docx(data, projection_limits=api.ProjectionLimits(max_nodes=1))
except api.ProjectionError as error:
    assert error.code == 'projection_limit_exceeded'
    assert MARKER not in str(error)
else:
    raise AssertionError('Node limit was not enforced')
""".replace("PAYLOAD", json.dumps(base64.b64encode(raw).decode())).replace(
        "MARKER", json.dumps(PRIVATE)
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "" and result.stderr == ""
