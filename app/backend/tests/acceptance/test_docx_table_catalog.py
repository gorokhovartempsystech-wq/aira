"""Independent direct-current table grid facts, never a visibility oracle."""

import json
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from docx_projection_fixtures import package
from test_docx_move_catalog import resolve

PRIVATE = "SYNTHETIC_PRIVATE_CELL"


def api():
    return import_module("ara.docx_analysis.tables")


def paragraph(text=PRIVATE):
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def cell(blocks=None, properties=""):
    prop = f"<w:tcPr>{properties}</w:tcPr>" if properties else ""
    return "<w:tc>" + prop + (paragraph() if blocks is None else blocks) + "</w:tc>"


def row(cells=None, properties="", attrs=""):
    prop = f"<w:trPr>{properties}</w:trPr>" if properties else ""
    return f"<w:tr {attrs}>" + prop + (cell() + cell() if cells is None else cells) + "</w:tr>"


def table(rows=None, columns=2, properties=""):
    prop = f"<w:tblPr>{properties}</w:tblPr>" if properties else ""
    grid = "<w:tblGrid>" + '<w:gridCol w:w="1000"/>' * columns + "</w:tblGrid>"
    return "<w:tbl>" + prop + grid + (row() + row() if rows is None else rows) + "</w:tbl>"


def source(body=None, **kwargs):
    return package(table() if body is None else body, main_part="custom/Tables.xml", **kwargs)


def read(raw, **kwargs):
    return api().read_table_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def digest(catalog):
    value = asdict(catalog)
    value.pop("catalog_sha256")
    return sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def error(code, call):
    with pytest.raises(api().TableCatalogError) as caught:
        call()
    assert caught.value.code == code and PRIVATE not in str(caught.value)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_two_by_two_exact_original_coordinates_and_manifest(strict, encoding):
    raw, xml = source(strict=strict, encoding=encoding)
    before = raw
    c = read(raw)
    assert (
        c.status == "indexed"
        and c.profile == "docx-tables/main-physical-grid-v1"
        and c.issues == ()
    )
    assert c == read(raw) and c.catalog_sha256 == digest(c) and not hasattr(c, "complete")
    (t,) = c.tables
    assert t.anchor.path == (0, 0) and t.parent_cell_anchor is None and t.properties_anchor is None
    assert t.grid_anchor.path == (0, 0, 0)
    assert [a.path for a in t.grid_columns] == [(0, 0, 0, 0), (0, 0, 0, 1)]
    root = ET.fromstring(xml)
    for ri, r in enumerate(t.rows):
        assert r.anchor.path == (0, 0, ri + 1)
        assert r.properties_anchor is None and (r.grid_before, r.grid_after) == (0, 0)
        for ci, x in enumerate(r.cells):
            assert x.anchor.path == (0, 0, ri + 1, ci)
            assert (x.column_start, x.column_span, x.vertical_merge) == (ci, 1, "none")
            assert x.merge_origin == x.anchor and x.properties_anchor is None
            (b,) = x.blocks
            assert b.kind == "paragraph" and b.anchor.path == x.anchor.path + (0,)
            assert resolve(root, b.anchor).tag.endswith("}p")
            assert (
                b.anchor.source_sha256 == sha256(raw).hexdigest()
                and b.anchor.part_name == "custom/Tables.xml"
            )
    assert PRIVATE not in repr(c) + repr(t) + repr(t.rows[0]) + repr(t.rows[0].cells[0])
    assert raw == before
    with pytest.raises(FrozenInstanceError):
        c.status = "changed"


def test_horizontal_span_vertical_chains_and_continuations_keep_own_blocks():
    span = '<w:gridSpan w:val="2"/>'
    rows = row(cell(paragraph("Origin"), span + '<w:vMerge w:val="restart"/>') + cell())
    rows += row(cell(paragraph("Continuation payload"), span + "<w:vMerge/>") + cell())
    rows += row(cell(paragraph("Third"), span + '<w:vMerge w:val="continue"/>') + cell())
    raw, xml = source(table(rows, columns=3))
    c = read(raw)
    assert c.status == "indexed"
    (t,) = c.tables
    origin = t.rows[0].cells[0].anchor
    assert [r.cells[0].vertical_merge for r in t.rows] == ["restart", "continue", "continue"]
    assert all((r.cells[0].column_start, r.cells[0].column_span) == (0, 2) for r in t.rows)
    assert all(r.cells[0].merge_origin == origin for r in t.rows)
    assert all(r.cells[1].column_start == 2 for r in t.rows)
    blocks = [r.cells[0].blocks[0].anchor for r in t.rows]
    assert [a.path for a in blocks] == [(0, 0, 1, 0, 1), (0, 0, 2, 0, 1), (0, 0, 3, 0, 1)]
    root = ET.fromstring(xml)
    assert ["".join(resolve(root, a).itertext()) for a in blocks] == [
        "Origin",
        "Continuation payload",
        "Third",
    ]


def test_gaps_are_not_cells_and_restart_resets_origin():
    props = '<w:gridBefore w:val="+01"/><w:gridAfter w:val="01"/>'
    first = row(cell(properties='<w:gridSpan w:val="02"/><w:vMerge w:val="restart"/>'), props)
    rows = first + first + row(cell(properties='<w:gridSpan w:val="2"/><w:vMerge/>'), props)
    (t,) = read(source(table(rows, columns=4))[0]).tables
    assert all(len(r.cells) == 1 and (r.grid_before, r.grid_after) == (1, 1) for r in t.rows)
    assert all((r.cells[0].column_start, r.cells[0].column_span) == (1, 2) for r in t.rows)
    assert t.rows[0].cells[0].merge_origin == t.rows[0].cells[0].anchor
    assert t.rows[2].cells[0].merge_origin == t.rows[1].cells[0].anchor


def test_nested_tables_preorder_parent_cells_and_mixed_block_order():
    nested = table(row(cell()), columns=1)
    outer = table(row(cell(paragraph("Before") + nested + paragraph("After"))), columns=1)
    raw, xml = source(outer + paragraph("Between") + table(row(cell()), columns=1))
    c = read(raw)
    assert c.status == "indexed" and len(c.tables) == 3
    outer, inner, sibling = c.tables
    assert outer.anchor.path == (0, 0) and sibling.anchor.path == (0, 2)
    parent = outer.rows[0].cells[0]
    assert inner.parent_cell_anchor == parent.anchor and sibling.parent_cell_anchor is None
    assert [b.kind for b in parent.blocks] == ["paragraph", "table", "paragraph"]
    assert parent.blocks[1].anchor == inner.anchor
    assert inner.anchor.path == (0, 0, 1, 0, 1)
    assert inner.rows[0].cells[0].column_start == 0
    root = ET.fromstring(xml)
    assert all(resolve(root, t.anchor).tag.endswith("}tbl") for t in c.tables)


def test_direct_properties_are_metadata_not_visibility_or_revision_inference():
    content = '<w:p><w:ins w:id="1"><w:r><w:t>Added</w:t></w:r></w:ins><w:del w:id="2"/></w:p>'
    rows = row(
        cell(content, '<w:shd w:fill="000000"/>'),
        "<w:hidden/>",
        'w:rsidDel="012345ab" w:rsidTr="87654321"',
    )
    raw, _ = source(table(rows, 1, '<w:tblStyle w:val="UnresolvedStyle"/><w:bidiVisual/>'))
    c = read(raw)
    assert c.status == "indexed" and not hasattr(c, "analysis_text")
    (t,) = c.tables
    assert t.properties_anchor.path == (0, 0, 0)
    assert t.rows[0].properties_anchor.path == (0, 0, 2, 0)
    assert t.rows[0].cells[0].properties_anchor.path == (0, 0, 2, 1, 0)
    assert t.rows[0].cells[0].blocks[0].kind == "paragraph"


@pytest.mark.parametrize(
    "body,code",
    [
        ("<w:tbl>" + row() + "</w:tbl>", "unresolved_table_grid"),
        (table(columns=0), "unresolved_table_grid"),
        (table(row(cell()), columns=2), "unresolved_table_grid"),
        (
            table(row(cell(properties='<w:gridSpan w:val="3"/>')), columns=2),
            "unresolved_table_grid",
        ),
        (table(row(properties='<w:gridAfter w:val="1"/>')), "unresolved_table_grid"),
        (table(row(cell(properties="<w:vMerge/>") + cell())), "invalid_vertical_merge"),
        (
            table(
                row(cell(properties='<w:vMerge w:val="restart"/>') + cell())
                + row()
                + row(cell(properties="<w:vMerge/>") + cell())
            ),
            "invalid_vertical_merge",
        ),
        (
            table(
                row(cell(properties='<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>'))
                + row(cell(properties="<w:vMerge/>") + cell())
            ),
            "invalid_vertical_merge",
        ),
        (
            table(row(cell(properties='<w:hMerge w:val="restart"/>') + cell())),
            "unsupported_table_revision",
        ),
        (table(row(properties='<w:del w:id="1"/>')), "unsupported_table_revision"),
        (table(row(properties='<w:ins w:id="1"/>')), "unsupported_table_revision"),
        (
            "<w:sdt><w:sdtContent>" + table() + "</w:sdtContent></w:sdt>",
            "unsupported_table_context",
        ),
        ('<w:del w:id="1">' + table() + "</w:del>", "unsupported_table_context"),
        (table(row(cell("<w:sdt/>") + cell())), "unsupported_table_context"),
    ],
)
def test_unsupported_or_ambiguous_table_shapes_never_partial(body, code):
    raw, xml = source(body)
    c = read(raw)
    assert c.status == "blocked" and c.tables == () and len(c.issues) == 1
    (issue,) = c.issues
    assert issue.code == code
    assert resolve(ET.fromstring(xml), issue.anchor) is not None
    assert c.catalog_sha256 == digest(c)


@pytest.mark.parametrize("value", ["0", "-1", "1.5", " 1", "1" * 21])
def test_invalid_span_lexemes(value):
    c = read(source(table(row(cell(properties=f'<w:gridSpan w:val="{value}"/>') + cell())))[0])
    assert c.status == "blocked" and c.issues[0].code == "invalid_table_markup"


def test_absent_does_not_mean_complete_and_legacy_readers_still_block_tables():
    from uuid import UUID

    raw, _ = source("<w:p><s:unknown/></w:p>")
    c = read(raw)
    assert c.status == "absent" and c.tables == () and not hasattr(c, "complete")
    raw, _ = source()
    kwargs = dict(
        document_id=UUID(int=1), storage_revision=1, source_sha256=sha256(raw).hexdigest()
    )
    old = import_module("ara.docx_analysis.visible_main")
    moved = import_module("ara.docx_analysis.visible_moves")
    assert not old.build_visible_snapshot(raw, **kwargs).complete
    assert not moved.build_move_snapshot(raw, **kwargs).complete
