"""Table controls retain the physical cell, source path and proven grid semantics."""

from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_current_tables import history
from test_docx_grid_tables import gridless
from test_docx_move_catalog import resolve
from test_docx_note_catalog import note
from test_docx_retained_tables import marker
from test_docx_section_catalog import BASE, reference, section
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_controls import control
from test_docx_visible_fields import char, instr
from test_docx_visible_main import DOC, R, canonical, codes, payload, source
from test_docx_visible_notes import fixture, literal, p, ref
from test_docx_visible_stories import story_xml
from test_docx_visible_styled_tables import table_style

PROFILE = "docx-analysis/final-visible-control-tables-v1"


def api():
    return import_module("ara.docx_analysis.visible_control_tables")


def build(raw, **kw):
    return api().build_control_table_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest(), **kw
    )


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


def blocked(body):
    s = build(source(body)[0])
    assert not s.complete and s.analysis_text == ""
    assert s.fragments == s.references == s.paragraphs == s.runs == ()
    return s


def one(text="Cell", props=""):
    return table(row(cell(paragraph(text), props)), columns=1)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
@pytest.mark.parametrize("level", ["body", "row", "cell", "cell_block", "all"])
def test_control_table_levels_keep_actual_source_cell_and_paths(strict, encoding, level):
    block = paragraph("Я😀")
    if level in ("cell_block", "all"):
        block = control(block)
    c = cell(block)
    if level in ("cell", "all"):
        c = control(c)
    r = row(c)
    if level in ("row", "all"):
        r = control(r)
    body = table(r, columns=1)
    if level in ("body", "all"):
        body = control(body)
    raw, xml = source(body, strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.analysis_text == "Я😀"
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    f = s.fragments[0]
    tree = ET.fromstring(xml)
    assert resolve(tree, f.flow_anchor).tag.endswith("}tc")
    assert resolve(tree, f.paragraph_anchor).tag.endswith("}p")
    assert resolve(tree, f.pieces[0].anchor).text == f.text
    mapped = api().map_control_table_span(
        raw, s, fragment_id=f.fragment_id, start=1, end=2, quote="😀"
    )
    assert mapped.slices[0].anchor == f.pieces[0].anchor
    assert (mapped.slices[0].start, mapped.slices[0].end) == (1, 2)
    assert ("metadata", "table_structure") in codes(s)


def test_mixed_controlled_rows_cells_and_nested_tables_preserve_source_order():
    inner = control(one("Nested"))
    first = row(
        cell(control(paragraph("A") + inner + paragraph("B"))) + control(cell(paragraph("C")))
    )
    second = control(row(control(cell(paragraph("D"))) + cell(paragraph("E"))))
    raw, xml = source(control(table(first + second)))
    s = build(raw)
    assert s.complete and s.analysis_text == "A\n\nNested\n\nB\n\nC\n\nD\n\nE"
    fs = s.fragments
    assert fs[0].flow_anchor == fs[2].flow_anchor
    assert len({f.flow_anchor for f in fs}) == 5
    tree = ET.fromstring(xml)
    assert all(resolve(tree, f.flow_anchor).tag.endswith("}tc") for f in fs)


def test_nested_row_and_cell_controls_resolve_single_original_subject():
    body = table(control(control(row(control(control(cell(paragraph("Nested"))))))), columns=1)
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Nested" and len(s.paragraphs) == 1


def test_empty_structural_controls_do_not_create_rows_cells_or_characters():
    body = control() + table(
        control() + row(control() + cell(control() + paragraph("A"))), columns=1
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "A"
    assert len(s.paragraphs) == 1 and ("metadata", "empty_control") in codes(s)


def test_controlled_table_keeps_neutral_style_and_property_history():
    props = '<w:tblStyle w:val="T"/>' + history("table", '<w:tblStyle w:val="UnknownOld"/>')
    cells = control(cell(paragraph("Styled")))
    body = control(table(control(row(cells)), columns=1, properties=props))
    s = build(source(body, table_style("T"))[0])
    assert s.complete and s.analysis_text == "Styled"
    assert ("metadata", "table_style_proven") in codes(s)
    assert ("excluded", "historical_table_properties") in codes(s)


def test_controlled_row_insertion_and_deleted_cell_preserve_retained_width():
    kept = control(cell(paragraph("Kept"), marker("cellIns")))
    deleted = control(cell(paragraph("Deleted"), marker("cellDel")))
    body = table(control(row(kept + deleted, marker("ins"))), columns=1)
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Kept"
    assert ("excluded", "deleted_table_cell") in codes(s)
    assert ("metadata", "inserted_table_row") in codes(s)


def test_controlled_table_can_infer_only_regular_retained_grid():
    body = gridless(control(row(control(cell(paragraph("A"))))))
    s = build(source(control(body))[0])
    assert s.complete and s.analysis_text == "A"
    assert ("metadata", "derived_table_grid") in codes(s)


def test_vertical_merge_uses_real_controlled_cells_and_empty_continuation():
    first = control(row(control(cell(paragraph("Origin"), '<w:vMerge w:val="restart"/>'))))
    second = control(row(control(cell("<w:p/>", "<w:vMerge/>"))))
    s = build(source(table(first + second, columns=1))[0])
    assert s.complete and s.analysis_text == "Origin"
    assert ("excluded", "merged_cell_continuation") in codes(s)
    blocked(
        table(
            first + control(row(control(cell(paragraph("Unresolved"), "<w:vMerge/>")))), columns=1
        )
    )


def test_controlled_tables_in_header_and_note_keep_correct_story_parts():
    body = p(ref()) + section(reference())
    raw = fixture(
        body,
        foot=note(content=control(one("Note"))),
        links=[
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
            {"Id": "H", "Type": R + "header", "Target": "H.xml"},
        ],
        extras={"custom/H.xml": story_xml(control(one("Header")))},
        types={"custom/H.xml": BASE + "header+xml"},
    )[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Header\n\nNote" and len(s.references) == 1
    assert [f.story_anchor.part_name for f in s.fragments] == ["custom/H.xml", "custom/Foot.xml"]
    assert s.references[0].target_anchor == s.fragments[1].story_anchor


def test_closed_field_spans_paragraphs_inside_one_controlled_cell():
    blocks = p(char("begin") + instr() + char("separate") + literal("A")) + p(
        literal("B") + char("end")
    )
    body = control(table(control(row(control(cell(control(blocks))))), columns=1))
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "A\n\nB"
    assert s.fragments[0].flow_anchor == s.fragments[1].flow_anchor


@pytest.mark.parametrize(
    "body",
    [
        table(control(row(cell(paragraph("A"))) + row(cell(paragraph("B")))), columns=1),
        table(row(control(cell(paragraph("A")) + cell(paragraph("B")))), columns=2),
        table(control(cell(paragraph("Cell in row role"))), columns=1),
        table(row(control(paragraph("Paragraph in cell role"))), columns=1),
        table(row(cell(control(row(cell(paragraph("Row in block role")))))), columns=1),
        control("<w:tblPr/>"),
        "<w:tbl>" + control("<w:tblGrid><w:gridCol/></w:tblGrid>") + row(cell()) + "</w:tbl>",
        "<w:tbl>"
        + control("<w:tblPr/>")
        + "<w:tblGrid><w:gridCol/></w:tblGrid>"
        + row(cell())
        + "</w:tbl>",
        table(control(row(cell(paragraph("A"))), "<w:dataBinding/>"), columns=1),
        table(row(control(cell(paragraph("A")), "<w:showingPlcHdr/>")), columns=1),
        table(row(control(cell(paragraph("A")), "<w:text/>")), columns=1),
        table(
            control(row(cell(paragraph("A")))) + row(cell(paragraph("B")) + cell(paragraph("C")))
        ),
    ],
)
def test_unresolved_role_grid_or_control_properties_are_atomic(body):
    blocked(p(literal("Prefix")) + body)


def test_one_control_may_not_hide_a_second_physical_cell_by_revision_filtering():
    cells = cell(paragraph("Removed"), marker("cellDel")) + cell(paragraph("Kept"))
    blocked(table(row(control(cells)), columns=1))


@pytest.mark.parametrize(
    "body",
    [
        "<w:tbl>"
        + control()
        + "<w:tblPr/><w:tblGrid><w:gridCol/></w:tblGrid>"
        + row(cell())
        + "</w:tbl>",
        "<w:tbl>" + control() + "<w:tblGrid><w:gridCol/></w:tblGrid>" + row(cell()) + "</w:tbl>",
        table("<w:tr>" + control() + "<w:trPr/>" + cell() + "</w:tr>", columns=1),
        table(row("<w:tc>" + control() + "<w:tcPr/>" + paragraph() + "</w:tc>"), columns=1),
    ],
)
def test_empty_controls_cannot_promote_late_structural_properties_or_grid(body):
    blocked(body)
