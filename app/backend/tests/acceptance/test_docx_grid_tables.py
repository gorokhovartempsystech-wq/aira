"""Logical columns derived from current retained spans never invent XML addresses."""

import json
from dataclasses import asdict
from hashlib import sha256
from importlib import import_module

import pytest
from test_docx_current_tables import cell, history, paragraph, row, source, table
from test_docx_retained_tables import marker


def api():
    return import_module("ara.docx_analysis.grid_tables")


def gridless(rows, properties=""):
    props = "<w:tblPr>" + properties + "</w:tblPr>" if properties else ""
    return "<w:tbl>" + props + rows + "</w:tbl>"


def fixture(mode="omitted", *, strict=False, encoding="utf-8"):
    rows = row(cell(paragraph("A")) + cell(paragraph("B")))
    rows += row(cell(paragraph("C")) + cell(paragraph("D")))
    body = (
        gridless(rows)
        if mode == "omitted"
        else table(rows, {"empty": 0, "short": 1, "exact": 2}[mode])
    )
    return source(body, strict=strict, encoding=encoding)


def read(raw, **kwargs):
    return api().read_grid_table_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def payload(c):
    value = asdict(c)
    value.pop("catalog_sha256")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def error(code, call):
    with pytest.raises(api().TableCatalogError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("mode", ["omitted", "empty", "short", "exact"])
@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_column_count_mode_and_only_actual_grid_anchors(mode, strict, encoding):
    raw, _ = fixture(mode, strict=strict, encoding=encoding)
    c = read(raw)
    assert c.profile == "docx-tables/current-resolved-grid-v1" and c.status == "indexed"
    assert c.issues == () and len(c.tables) == 1
    t = c.tables[0]
    assert t.column_count == 2 and len(t.rows) == 2
    assert (
        t.grid_mode
        == {"omitted": "inferred", "empty": "augmented", "short": "augmented", "exact": "explicit"}[
            mode
        ]
    )
    count = {"omitted": 0, "empty": 0, "short": 1, "exact": 2}[mode]
    assert [a.path for a in t.grid_columns] == [(0, 0, 0, i) for i in range(count)]
    if mode == "omitted":
        assert t.grid_anchor is None
        assert t.rows[0].anchor.path == (0, 0, 0)
    else:
        assert t.grid_anchor.path == (0, 0, 0)
        assert t.rows[0].anchor.path == (0, 0, 1)
    assert [x.column_start for x in t.rows[0].cells] == [0, 1]
    assert c.catalog_sha256 == sha256(payload(c)).hexdigest() and read(raw) == c


def test_spans_and_vertical_origins_do_not_require_fabricated_columns():
    rows = row(cell(paragraph("Origin"), '<w:gridSpan w:val="3"/><w:vMerge w:val="restart"/>'))
    rows += row(cell("<w:p/>", '<w:gridSpan w:val="3"/><w:vMerge/>'))
    c = read(source(gridless(rows))[0])
    t = c.tables[0]
    assert t.column_count == 3 and t.grid_columns == () and t.grid_anchor is None
    a, b = (r.cells[0] for r in t.rows)
    assert a.column_span == b.column_span == 3 and b.merge_origin == a.anchor
    assert a.anchor.path == (0, 0, 0, 0)


def test_nested_grids_resolve_independently_and_keep_parent_cell():
    nested = gridless(row(cell(paragraph("Nested"))))
    outer = gridless(row(cell(paragraph("Outer") + nested) + cell(paragraph("Right"))))
    c = read(source(outer)[0])
    assert c.status == "indexed" and [t.column_count for t in c.tables] == [2, 1]
    a, b = c.tables
    assert b.parent_cell_anchor == a.rows[0].cells[0].anchor
    assert a.grid_anchor is b.grid_anchor is None


def test_previous_grid_and_deleted_span_are_not_sources_for_current_column_count():
    removed = cell(paragraph("OLD"), marker("cellDel") + '<w:gridSpan w:val="99"/>')
    rows = row(removed + cell(paragraph("A")) + cell(paragraph("B")))
    body = table(rows, 0).replace(
        "</w:tblGrid>", history("grid", "<w:gridCol/>" * 8) + "</w:tblGrid>", 1
    )
    c = read(source(body)[0])
    assert c.status == "indexed" and c.tables[0].column_count == 2
    assert c.tables[0].grid_mode == "augmented" and c.tables[0].grid_columns == ()
    assert len(c.histories) == len(c.revisions) == 1


@pytest.mark.parametrize(
    "body",
    [
        gridless(row(cell()) + row(cell() + cell())),
        gridless(row(cell(), '<w:gridBefore w:val="1"/>')),
        gridless(row(cell(), '<w:gridAfter w:val="1"/>')),
        table(row(cell()), 2),
        table(row(cell(), '<w:gridBefore w:val="1"/>'), 1),
    ],
)
def test_ambiguous_row_widths_gaps_and_oversized_current_grid_stay_blocked(body):
    c = read(source(table() + body)[0])
    assert c.status == "blocked" and c.tables == c.histories == c.revisions == ()
    assert c.issues[0].code == "unresolved_table_grid"


def test_existing_explicit_grid_with_valid_gaps_stays_explicit():
    rows = row(cell(), '<w:gridBefore w:val="1"/><w:gridAfter w:val="1"/>')
    c = read(source(table(rows, 3))[0])
    assert c.status == "indexed" and c.tables[0].grid_mode == "explicit"
    r = c.tables[0].rows[0]
    assert r.grid_before == r.grid_after == 1 and r.cells[0].column_start == 1


@pytest.mark.parametrize(
    "grid",
    [
        "<w:tblGrid>TEXT</w:tblGrid>",
        '<w:tblGrid w:extra="x"/>',
        "<w:tblGrid><w:unknown/></w:tblGrid>",
        "<w:tblGrid><w:gridCol><w:unknown/></w:gridCol></w:tblGrid>",
        "<w:tblGrid/><w:tblGrid/>",
    ],
)
def test_malformed_current_grid_is_not_replaced_by_inference(grid):
    c = read(source("<w:tbl>" + grid + row(cell()) + "</w:tbl>")[0])
    assert c.status == "blocked" and c.tables == ()


def test_misordered_grid_and_invalid_current_merge_still_block():
    c = read(source("<w:tbl>" + row(cell()) + "<w:tblGrid/>" + "</w:tbl>")[0])
    assert c.status == "blocked" and c.tables == ()
    c = read(source(gridless(row(cell(properties="<w:vMerge/>"))))[0])
    assert c.status == "blocked" and c.issues[0].code == "invalid_vertical_merge"


def test_old_retained_grid_profile_is_unchanged_and_limits_are_exact():
    old = import_module("ara.docx_analysis.retained_tables")
    for mode in ("omitted", "empty", "short"):
        raw = fixture(mode)[0]
        assert (
            old.read_retained_table_catalog(raw, source_sha256=sha256(raw).hexdigest()).status
            == "blocked"
        )
    error(
        "invalid_input",
        lambda: old.read_retained_table_catalog(
            raw, source_sha256=sha256(raw).hexdigest(), limits=api().GridTableLimits()
        ),
    )
    error("invalid_input", lambda: read(raw, limits=old.RetainedTableLimits()))
