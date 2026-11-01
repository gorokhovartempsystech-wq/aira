"""Additional synthetic regressions for boundaries of structural projection."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from ara.docx_package import export_original
from ara.docx_package.projection import ProjectionError, ProjectionLimits, _parse, project_docx

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT = "http://purl.oclc.org/ooxml/wordprocessingml/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STRICT_REL = "http://purl.oclc.org/ooxml/officeDocument/relationships"


def package(body, *, before="", after="", strict=False):
    word, rel = (STRICT, STRICT_REL) if strict else (WORD, REL)
    main = (
        f'<w:document xmlns:w="{word}" xmlns:r="{rel}" xmlns:x="urn:test">'
        f"{before}<w:body>{body}</w:body>{after}</w:document>"
    ).encode()
    types = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Override PartName="/main.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="main" Type="{rel}/officeDocument" Target="main.xml"/>'
        "</Relationships>"
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("main.xml", main)
    return buffer.getvalue()


def test_strict_hyperlink_preserves_literal_metadata_and_malformed_leaf_boundary():
    raw = package(
        '<w:p><w:hyperlink r:id="id-7" w:anchor="local">'
        "<w:r><w:t>😀</w:t><w:tab><x:child>hidden</x:child></w:tab>"
        '<w:br w:type=""/><w:t/></w:r></w:hyperlink></w:p>',
        strict=True,
    )
    result = project_docx(raw)
    node = result.blocks[0]
    assert node.text == "😀\ufffc\n"
    assert [(s.start, s.end) for s in node.spans] == [(0, 1), (1, 2), (2, 3), (3, 3)]
    assert node.spans[1].reason == "unsupported_structure"
    assert node.spans[1].anchor.path == (0, 0, 0, 0, 1)
    assert all(s.hyperlink.relationship_id == "id-7" for s in node.spans)
    assert all(s.hyperlink.bookmark == "local" for s in node.spans)
    assert node.spans[2].break_type == ""  # Literal value, not an effective layout.
    assert "hidden" not in repr(result)
    assert export_original(result.source) == raw


@pytest.mark.parametrize("name", ["fldChar", "instrText", "ins", "pPrChange", "moveToRangeEnd"])
def test_foreign_namespace_lookalikes_do_not_activate_word_policies(name):
    result = project_docx(package(f"<w:p><w:r><x:{name}>hidden</x:{name}></w:r></w:p>"))
    node = result.blocks[0]
    assert node.kind == "paragraph" and node.text == "\ufffc"
    assert node.spans[0].reason == "unsupported_element"
    assert len(result.notices) == 1


def test_fields_outside_body_do_not_hide_body_and_notices_remain_in_source_order():
    result = project_docx(
        package(
            "<w:p><w:r><w:fldChar/></w:r></w:p>",
            before="<x:first><w:instrText>hidden</w:instrText></x:first>",
            after="<x:last/>",
        )
    )
    assert [(n.code, n.anchor.path) for n in result.notices] == [
        ("unprojected_root_element", (0,)),
        ("complex_field", (1,)),
        ("unprojected_root_element", (2,)),
    ]
    ordinary = project_docx(
        package("<w:p/>", before="<x:first><w:instrText>hidden</w:instrText></x:first>")
    )
    assert ordinary.blocks[0].kind == "paragraph"


def test_revision_in_nested_table_properties_only_blocks_that_table():
    result = project_docx(
        package(
            "<w:tbl><w:tr><w:tc><w:p/><w:tbl><w:tblPr><w:tblPrChange/>"
            "</w:tblPr><w:tblPr/></w:tbl><w:p/></w:tc></w:tr></w:tbl>"
        )
    )
    blocks = result.blocks[0].rows[0].cells[0].blocks
    assert [b.kind for b in blocks] == ["paragraph", "opaque", "paragraph"]
    assert blocks[1].reason == "tracked_change"
    assert [(n.code, n.anchor.path) for n in result.notices] == [
        ("tracked_change", (0, 0, 0, 0, 1))
    ]


def test_duplicate_run_properties_in_unknown_wrapper_do_not_block_surrounding_paragraph():
    result = project_docx(
        package(
            "<w:p><w:r><w:t>left</w:t></w:r><x:wrapper><w:r><w:rPr/><w:rPr/>"
            "<w:t>hidden</w:t></w:r></x:wrapper><w:r><w:t>right</w:t></w:r></w:p>"
        )
    )
    assert result.blocks[0].text == "left\ufffcright"
    assert len(result.notices) == 1
    assert result.notices[0].code == "unsupported_element"


@pytest.mark.parametrize("leaf", ["t", "tab", "br", "cr"])
@pytest.mark.parametrize("container", ["p", "hyperlink"])
def test_malformed_leaves_remain_opaque_also_outside_runs(leaf, container):
    content = f"<w:{leaf}>hidden<x:child/></w:{leaf}>"
    if container == "hyperlink":
        content = f"<w:hyperlink>{content}</w:hyperlink>"
    result = project_docx(package(f"<w:p>{content}</w:p>"))
    span = result.blocks[0].spans[0]
    assert span.text == "\ufffc" and span.reason == "unsupported_structure"
    assert span.run_anchor is None
    assert len(result.notices) == 1
    assert "hidden" not in repr(result)


def test_xml_comments_and_processing_instructions_do_not_consume_node_budget():
    raw = package("<!-- ignored --><?synthetic ignored?><w:p><w:r><w:t/></w:r></w:p>")
    result = project_docx(raw, projection_limits=ProjectionLimits(max_nodes=5, max_depth=5))
    assert result.blocks[0].spans[0].anchor.path == (0, 0, 0, 0)
    assert result.notices == ()


@pytest.mark.parametrize("field", ["max_nodes", "max_depth"])
def test_limits_are_revalidated_if_constructor_validation_was_bypassed(field):
    limits = ProjectionLimits()
    object.__setattr__(limits, field, True)
    with pytest.raises(ProjectionError) as caught:
        project_docx(package(""), projection_limits=limits)
    assert caught.value.code == "invalid_input"


@pytest.mark.parametrize("field", ["max_nodes", "max_depth"])
def test_parser_stops_consuming_main_part_when_tree_budget_is_exceeded(monkeypatch, field):
    # This part spans multiple decompression chunks. The first unknown wrapper
    # already crosses the budget; its large tail must never be tree-parsed.
    raw = package("<x:wrapper>" * 8 + "<x:child/>" * 30000 + "</x:wrapper>" * 8)
    original_chunks = _parse.chunks
    consumed = 0

    def observed_chunks(*args, **kwargs):
        nonlocal consumed
        for chunk in original_chunks(*args, **kwargs):
            consumed += 1
            assert consumed == 1, "Projection read past its first over-budget chunk"
            yield chunk

    monkeypatch.setattr(_parse, "chunks", observed_chunks)
    with pytest.raises(ProjectionError) as caught:
        project_docx(raw, projection_limits=ProjectionLimits(**{field: 4}))
    assert caught.value.code == "projection_limit_exceeded"
    assert consumed == 1
