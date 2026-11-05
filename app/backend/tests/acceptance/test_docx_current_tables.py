"""Current table properties are independent of exact original historical payloads."""

import json
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_main import source

KINDS = {"table": "tblPr", "grid": "tblGrid", "row": "trPr", "cell": "tcPr"}
PROFILE = "docx-tables/current-properties-grid-v1"


def api():
    return import_module("ara.docx_analysis.current_tables")


def history(kind, previous="", attrs='w:id="41"'):
    name = KINDS[kind]
    return f"<w:{name}Change {attrs}><w:{name}>{previous}</w:{name}></w:{name}Change>"


def fixture(*, strict=False, encoding="utf-8", styles=None):
    cells = cell(
        paragraph("A"),
        '<w:tcW w:w="1000"/>'
        + history("cell", '<w:gridSpan w:val="3"/><w:vMerge/><w:cellDel w:id="9"/>'),
    ) + cell(paragraph("B"))
    rows = row(cells, "<w:cantSplit/>" + history("row", "<w:hidden/>"))
    body = table(
        rows, 2, '<w:tblStyle w:val="Good"/>' + history("table", '<w:tblStyle w:val="Bad"/>')
    )
    body = body.replace(
        "</w:tblGrid>", history("grid", '<w:gridCol w:w="9000"/>') + "</w:tblGrid>", 1
    )
    return source(
        paragraph("Before") + body + paragraph("After"), styles, strict=strict, encoding=encoding
    )


def read(raw, **kwargs):
    return api().read_current_table_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def error(code, call):
    with pytest.raises(api().TableCatalogError) as caught:
        call()
    assert caught.value.code == code


def payload(c):
    d = asdict(c)
    d.pop("catalog_sha256")
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_exact_current_grid_and_all_four_history_source_anchors(strict, encoding):
    raw, xml = fixture(strict=strict, encoding=encoding)
    c = read(raw)
    assert c.status == "indexed" and c.profile == PROFILE and c.issues == ()
    assert len(c.tables) == 1 and c.main_part == "custom/Main.xml"
    t = c.tables[0]
    assert len(t.grid_columns) == 2 and len(t.rows) == 1
    assert [cell.column_span for cell in t.rows[0].cells] == [1, 1]
    assert all(
        cell.vertical_merge == "none" and cell.merge_origin == cell.anchor
        for cell in t.rows[0].cells
    )
    assert [h.kind for h in c.histories] == ["table", "grid", "row", "cell"]
    paths = [(0, 1, 0, 1), (0, 1, 1, 2), (0, 1, 2, 0, 1), (0, 1, 2, 1, 0, 1)]
    root = ET.fromstring(xml)
    for h, path in zip(c.histories, paths, strict=True):
        assert h.anchor.path == path and h.owner_anchor.path == path[:-1]
        assert h.previous_anchor.path == path + (0,)
        assert h.anchor.source_sha256 == c.source_sha256 and h.anchor.part_name == c.main_part
        assert resolve(root, h.anchor).tag.endswith("}" + KINDS[h.kind] + "Change")
        assert resolve(root, h.previous_anchor).tag.endswith("}" + KINDS[h.kind])
    assert [a.path for a in t.grid_columns] == [(0, 1, 1, 0), (0, 1, 1, 1)]
    assert c.catalog_sha256 == sha256(payload(c)).hexdigest() and read(raw) == c
    assert sha256(raw).hexdigest() == c.source_sha256
    assert not hasattr(c, "complete") and not hasattr(c, "analysis_text")
    with pytest.raises(FrozenInstanceError):
        c.histories[0].kind = "changed"
    assert not hasattr(c.histories[0], "__dict__")


def test_current_spans_and_vertical_origin_do_not_use_historical_merge():
    old = history("cell", '<w:gridSpan w:val="99"/><w:vMerge w:val="continue"/>')
    rows = row(
        cell(paragraph("Origin"), '<w:gridSpan w:val="2"/><w:vMerge w:val="restart"/>' + old)
    )
    rows += row(
        cell(
            "<w:p/>",
            '<w:gridSpan w:val="2"/><w:vMerge/>' + history("cell", '<w:vMerge w:val="restart"/>'),
        )
    )
    c = read(source(table(rows, 2))[0])
    assert c.status == "indexed" and len(c.histories) == 2
    first, second = (r.cells[0] for r in c.tables[0].rows)
    assert first.column_span == second.column_span == 2
    assert second.vertical_merge == "continue" and second.merge_origin == first.anchor


def test_previous_opaque_properties_are_not_activated_or_exposed():
    previous = '<w:unknown w:secret="SYNTHETIC_PRIVATE_HISTORY"><w:tbl><w:tr><w:tc/>'
    previous += "</w:tr></w:tbl><w:p><w:r><w:t>OLD PRIVATE TEXT</w:t></w:r></w:p></w:unknown>"
    raw = source(
        table(properties=history("table", previous, 'w:id="1" w:author="PRIVATE AUTHOR"'))
    )[0]
    c = read(raw)
    assert c.status == "indexed" and len(c.tables) == 1 and len(c.histories) == 1
    assert b"PRIVATE" not in payload(c) and "PRIVATE" not in repr(c) + repr(c.histories[0])


@pytest.mark.parametrize("kind", list(KINDS))
def test_history_outside_actual_current_owner_is_blocked(kind):
    body = paragraph("Prefix") + "<w:p>" + history(kind) + "</w:p>"
    c = read(source(body)[0])
    assert c.status == "blocked" and c.tables == c.histories == ()
    assert c.issues[0].code == "unsupported_table_context"


@pytest.mark.parametrize(
    "marker",
    [
        "<w:tcPrChange><w:tcPr/></w:tcPrChange>",
        '<w:tcPrChange w:id="x"><w:tcPr/></w:tcPrChange>',
        '<w:tcPrChange w:id="1"><w:trPr/></w:tcPrChange>',
        '<w:tcPrChange w:id="1"><w:tcPr/><w:tcPr/></w:tcPrChange>',
        '<w:tcPrChange w:id="1" w:extra="x"><w:tcPr/></w:tcPrChange>',
        '<w:tcPrChange w:id="1">TEXT<w:tcPr/></w:tcPrChange>',
        '<w:tcPrChange w:id="1"><w:tcPr w:extra="x"/></w:tcPrChange>',
        '<w:tcPrChange w:id="1"><w:tcPr>TEXT</w:tcPr></w:tcPrChange>',
        history("cell") + history("cell"),
        history("cell") + '<w:tcW w:w="1"/>',
    ],
)
def test_malformed_duplicate_or_misordered_history_never_returns_partial_proof(marker):
    body = table() + table(row(cell(properties=marker)), 1)
    c = read(source(body)[0])
    assert c.status == "blocked" and c.tables == c.histories == ()
    assert c.issues[0].code == "invalid_table_history"


def test_grid_history_has_only_id_and_cannot_supply_missing_current_grid():
    for marker in (
        history("grid", attrs='w:id="1" w:author="Synthetic"'),
        history("grid", attrs='w:id="1" w:date="2026-11-04T00:00:00Z"'),
    ):
        body = table().replace("</w:tblGrid>", marker + "</w:tblGrid>", 1)
        c = read(source(body)[0])
        assert c.status == "blocked" and c.issues[0].code == "invalid_table_history"
    body = table(row(cell()), 1).replace(
        '<w:gridCol w:w="1000"/>', history("grid", '<w:gridCol w:w="1"/>')
    )
    c = read(source(body)[0])
    assert c.status == "blocked" and c.issues[0].code == "unresolved_table_grid"


def test_historical_geometry_never_repairs_invalid_current_geometry():
    body = table(
        row(
            cell(properties='<w:gridSpan w:val="3"/>' + history("cell", '<w:gridSpan w:val="2"/>'))
        ),
        2,
    )
    c = read(source(body)[0])
    assert c.status == "blocked" and c.tables == c.histories == ()
    assert c.issues[0].code == "unresolved_table_grid"


@pytest.mark.parametrize(
    "kind,marker",
    [
        ("row", '<w:ins w:id="1"/>'),
        ("row", '<w:del w:id="1"/>'),
        ("cell", '<w:cellIns w:id="1"/>'),
        ("cell", '<w:cellDel w:id="1"/>'),
        ("cell", '<w:cellMerge w:id="1"/>'),
        ("cell", "<w:hMerge/>"),
    ],
)
def test_current_structural_revisions_are_still_unresolved(kind, marker):
    props = marker + history(kind)
    body = table(row(properties=props)) if kind == "row" else table(row(cell(properties=props)), 1)
    c = read(source(body)[0])
    assert c.status == "blocked" and c.issues[0].code == "unsupported_table_revision"


def test_legacy_profile_and_limits_do_not_silently_admit_histories():
    old = import_module("ara.docx_analysis.tables")
    raw = fixture()[0]
    previous = old.read_table_catalog(raw, source_sha256=sha256(raw).hexdigest())
    assert previous.status == "blocked" and previous.issues[0].code == "unsupported_table_revision"
    assert read(raw).status == "indexed"
    error(
        "invalid_input",
        lambda: old.read_table_catalog(
            raw, source_sha256=sha256(raw).hexdigest(), limits=api().CurrentTableLimits()
        ),
    )
    c = read(source(paragraph("No tables"))[0])
    assert c.status == "absent" and c.tables == c.histories == c.issues == ()
