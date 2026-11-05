"""Final logical cells retain original physical addresses around tracked deletions."""

import json
from dataclasses import asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_current_tables import cell, history, paragraph, row, source, table
from test_docx_move_catalog import resolve


def api():
    return import_module("ara.docx_analysis.retained_tables")


def marker(kind, attrs='w:id="1"'):
    return f"<w:{kind} {attrs}/>"


def fixture(*, strict=False, encoding="utf-8", old_text="DELETED_PRIVATE"):
    a = cell(paragraph("A"), marker("cellIns") + history("cell", marker("cellDel")))
    deleted = cell(
        paragraph(old_text) + "<w:tbl><w:unknown/></w:tbl>",
        '<w:gridSpan w:val="99"/>' + marker("cellDel", 'w:id="2"') + history("cell"),
    )
    b = cell(paragraph("B"))
    rows = row(a + deleted + b, marker("ins")) + row(cell(paragraph("C")) + cell(paragraph("D")))
    body = table(rows, 2, history("table"))
    return source(paragraph("Before") + body + paragraph("After"), strict=strict, encoding=encoding)


def read(raw, **kwargs):
    return api().read_retained_table_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def payload(c):
    value = asdict(c)
    value.pop("catalog_sha256")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def error(code, call):
    with pytest.raises(api().TableCatalogError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_retained_grid_revision_records_and_literal_source_addresses(strict, encoding):
    raw, xml = fixture(strict=strict, encoding=encoding)
    c = read(raw)
    assert c.status == "indexed" and c.profile == "docx-tables/retained-current-grid-v1"
    assert c.issues == () and len(c.tables) == 1 and len(c.histories) == 2
    t = c.tables[0]
    assert len(t.rows) == 2 and len(t.grid_columns) == 2
    assert [x.column_start for x in t.rows[0].cells] == [0, 1]
    assert [x.anchor.path for x in t.rows[0].cells] == [(0, 1, 2, 1), (0, 1, 2, 3)]
    assert [x.kind for x in c.revisions] == ["inserted_row", "inserted_cell", "deleted_cell"]
    expected = [
        ((0, 1, 2, 0, 0), (0, 1, 2, 0), (0, 1, 2)),
        ((0, 1, 2, 1, 0, 0), (0, 1, 2, 1, 0), (0, 1, 2, 1)),
        ((0, 1, 2, 2, 0, 1), (0, 1, 2, 2, 0), (0, 1, 2, 2)),
    ]
    root = ET.fromstring(xml)
    for record, paths in zip(c.revisions, expected, strict=True):
        assert (record.anchor.path, record.owner_anchor.path, record.subject_anchor.path) == paths
        assert record.anchor.source_sha256 == c.source_sha256
        assert record.anchor.part_name == c.main_part == "custom/Main.xml"
        assert resolve(root, record.subject_anchor).tag.endswith(
            "}tr" if record.kind == "inserted_row" else "}tc"
        )
    assert c.catalog_sha256 == sha256(payload(c)).hexdigest() and read(raw) == c
    assert b"PRIVATE" not in payload(c) and "PRIVATE" not in repr(c)


@pytest.mark.parametrize("kind", ["ins", "cellIns", "cellDel"])
@pytest.mark.parametrize("attrs", ["", 'w:id="x"', 'w:id="1" w:extra="x"'])
def test_invalid_revision_never_returns_partial_records(kind, attrs):
    values = marker(kind, attrs)
    if kind == "ins":
        body = table(row(properties=values))
    else:
        body = table(row(cell(properties=values) + cell()), 1 if kind == "cellDel" else 2)
    c = read(source(table() + body)[0])
    assert c.status == "blocked" and c.tables == c.histories == c.revisions == ()
    assert c.issues[0].code == "invalid_table_revision"


@pytest.mark.parametrize(
    "properties",
    [
        marker("cellDel") * 2,
        marker("cellIns") + marker("cellDel"),
        marker("cellDel") + marker("cellMerge"),
        marker("cellDel") + "<w:hMerge/>",
        '<w:cellDel w:id="1"><w:r/></w:cellDel>',
    ],
)
def test_conflicting_or_nonleaf_deletion_cannot_hide_payload(properties):
    c = read(source(table(row(cell(properties=properties) + cell()), 1))[0])
    assert c.status == "blocked" and c.issues[0].code == "invalid_table_revision"


def test_deleted_cell_does_not_fill_grid_or_repair_vertical_origin():
    raw = source(table(row(cell(properties=marker("cellDel")) + cell()), 2))[0]
    c = read(raw)
    assert c.status == "blocked" and c.issues[0].code == "unresolved_table_grid"
    rows = row(cell(properties=marker("cellDel") + '<w:vMerge w:val="restart"/>') + cell())
    rows += row(cell(properties="<w:vMerge/>"))
    c = read(source(table(rows, 1))[0])
    assert c.status == "blocked" and c.issues[0].code == "invalid_vertical_merge"


@pytest.mark.parametrize(
    "body",
    [
        table(row(cell(properties=marker("cellDel"))), 1),
        table(row(properties=marker("del"))),
        table(row(cell(properties=marker("cellMerge"))), 1),
        table(row(cell(properties="<w:hMerge/>")), 1),
    ],
)
def test_unresolved_row_boundary_and_merge_are_explicit_blockers(body):
    c = read(source(body)[0])
    assert c.status == "blocked" and c.tables == c.histories == c.revisions == ()


def test_fake_owner_mixed_namespace_and_duplicate_current_properties():
    raw = source("<w:p><w:tcPr>" + marker("cellDel") + "</w:tcPr></w:p>")[0]
    assert read(raw).issues[0].code == "unsupported_table_context"
    foreign = '<z:cellDel xmlns:z="http://purl.oclc.org/ooxml/wordprocessingml/main" z:id="1"/>'
    c = read(source(table(row(cell(properties=foreign) + cell()), 1))[0])
    assert c.status == "blocked" and c.issues[0].code == "unsupported_table_context"
    malformed = "<w:tc><w:tcPr>" + marker("cellDel") + "</w:tcPr><w:tcPr/><w:p/></w:tc>"
    c = read(source(table(row(malformed + cell()), 1))[0])
    assert c.status == "blocked" and c.revisions == ()


def test_old_current_profile_is_not_widened_and_absent_is_not_final_visibility():
    old = import_module("ara.docx_analysis.current_tables")
    raw = fixture()[0]
    assert (
        old.read_current_table_catalog(raw, source_sha256=sha256(raw).hexdigest()).status
        == "blocked"
    )
    error(
        "invalid_input",
        lambda: old.read_current_table_catalog(
            raw, source_sha256=sha256(raw).hexdigest(), limits=api().RetainedTableLimits()
        ),
    )
    c = read(source(paragraph("Body"))[0])
    assert c.status == "absent" and c.tables == c.revisions == c.histories == ()
    assert not hasattr(c, "complete") and not hasattr(c, "analysis_text")
