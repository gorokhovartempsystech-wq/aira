"""Global table-context scan, technical bounds and inert source-only reading."""

import os
import subprocess
import sys
from dataclasses import fields
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_table_catalog import api, cell, error, paragraph, read, row, source, table


@pytest.mark.parametrize(
    "properties",
    [
        '<w:gridSpan w:val="1"/><w:gridSpan w:val="1"/>',
        '<w:vMerge w:val="restart"/><w:vMerge/>',
        '<w:vMerge w:val="bogus"/>',
        "<w:gridSpan/>",
        '<w:gridSpan w:val="1"><w:r/></w:gridSpan>',
        '<w:gridSpan w:val="1" w:extra="x"/>',
    ],
)
def test_duplicate_malformed_geometry_is_not_guessed(properties):
    c = read(source(table(row(cell(properties=properties) + cell())))[0])
    assert c.status == "blocked" and c.issues[0].code == "invalid_table_markup"


@pytest.mark.parametrize(
    "kind,child",
    [
        ("tblPr", '<w:tblPrChange w:id="1"><w:tblPr/></w:tblPrChange>'),
        ("tblGrid", '<w:tblGridChange w:id="1"><w:tblGrid/></w:tblGridChange>'),
        ("trPr", '<w:trPrChange w:id="1"><w:trPr/></w:trPrChange>'),
        ("tcPr", '<w:tcPrChange w:id="1"><w:tcPr/></w:tcPrChange>'),
        ("tcPr", '<w:cellIns w:id="1"/>'),
        ("tcPr", '<w:cellDel w:id="1"/>'),
        ("tcPr", '<w:cellMerge w:id="1"/>'),
    ],
)
def test_table_revisions_block_before_historical_structure(kind, child):
    if kind == "tblPr":
        body = table(properties=child)
    elif kind == "tblGrid":
        body = table().replace("</w:tblGrid>", child + "</w:tblGrid>")
    elif kind == "trPr":
        body = table(row(properties=child))
    else:
        body = table(row(cell(properties=child) + cell()))
    c = read(source(body)[0])
    assert (
        c.status == "blocked"
        and c.tables == ()
        and c.issues[0].code == "unsupported_table_revision"
    )


def test_context_scan_rejects_nested_properties_and_mixed_word_namespaces():
    body = table(properties='<w:unknown><w:tcPr><w:gridSpan w:val="1"/></w:tcPr></w:unknown>')
    assert read(source(body)[0]).issues[0].code == "unsupported_table_context"
    body = (
        table()
        .replace("<w:tc>", '<z:tc xmlns:z="http://purl.oclc.org/ooxml/wordprocessingml/main">', 1)
        .replace("</w:tc>", "</z:tc>", 1)
    )
    c = read(source(body)[0])
    assert c.status == "blocked" and c.issues[0].code == "unsupported_table_context"


def test_width_does_not_control_column_index_and_comments_do_not_shift_paths():
    body = "<!-- synthetic -->" + table().replace('w:w="1000"', 'w:w="987654"')
    raw, _ = source(body)
    c = read(raw)
    assert c.status == "indexed" and c.tables[0].anchor.path == (0, 0)
    assert [x.column_start for x in c.tables[0].rows[0].cells] == [0, 1]


def test_xml_and_record_limits_include_unread_payload():
    raw, _ = source(table(row(cell(paragraph("X" * 2000)) + cell())))
    for limit in (
        dict(max_xml_nodes=2),
        dict(max_xml_depth=3),
        dict(max_xml_characters=1024),
        dict(max_rows=1),
        dict(max_cells=1),
        dict(max_grid_columns=1),
        dict(max_blocks=1),
    ):
        # There are two rows for the row cap; other cases retain the large cell.
        data = source()[0] if "max_rows" in limit else raw
        error(
            "table_limit_exceeded",
            lambda data=data, limit=limit: read(data, limits=api().TableLimits(**limit)),
        )
    error(
        "table_limit_exceeded",
        lambda: read(source(table() + table())[0], limits=api().TableLimits(max_tables=1)),
    )
    nested = table(row(cell(table(row(cell()), 1))), 1)
    error(
        "table_limit_exceeded",
        lambda: read(source(nested)[0], limits=api().TableLimits(max_table_depth=1)),
    )
    error("table_limit_exceeded", lambda: read(raw, limits=api().TableLimits(max_manifest_bytes=1)))


@pytest.mark.parametrize("what", ["nodes", "namespace", "excluded_cells"])
def test_preflight_rejects_before_semantic_dom(monkeypatch, what):
    parser = import_module("ara.docx_package.projection._parse")

    def forbidden(*args, **kwargs):
        raise AssertionError("Table DOM allocated before its budget")

    monkeypatch.setattr(parser, "_BoundedBuilder", forbidden)
    if what == "nodes":
        body, kwargs = table(), dict(max_xml_nodes=2)
    elif what == "namespace":
        body = table().replace("<w:tbl>", '<w:tbl xmlns:huge="' + "x" * 4096 + '">')
        kwargs = dict(max_xml_characters=1024)
    else:
        body = '<w:del w:id="1">' + table() + "</w:del>"
        kwargs = dict(max_cells=1)
    error("table_limit_exceeded", lambda: read(source(body)[0], limits=api().TableLimits(**kwargs)))


def test_input_and_mutated_limits_are_exact_and_source_pinned():
    from hashlib import sha256

    raw, _ = source()
    for data, digest in ((bytearray(raw), sha256(raw).hexdigest()), (raw, "A" * 64), (raw, None)):
        error(
            "invalid_input",
            lambda data=data, digest=digest: api().read_table_catalog(data, source_sha256=digest),
        )
    error("source_mismatch", lambda: api().read_table_catalog(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: read(raw, limits={}))
    for item in fields(api().TableLimits):
        error("invalid_input", lambda item=item: api().TableLimits(**{item.name: True}))
    limits = api().TableLimits()
    object.__setattr__(limits, "max_cells", 0)
    error("invalid_input", lambda: read(raw, limits=limits))


def test_package_errors_do_not_become_absent():
    from hashlib import sha256

    from ara.docx_package import DocxError

    raw = b"not a DOCX package"
    with pytest.raises(DocxError):
        api().read_table_catalog(raw, source_sha256=sha256(raw).hexdigest())


def test_fresh_process_inert_read_without_application_io():
    raw, _ = source()
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.tables import read_table_catalog
c=read_table_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="indexed" and len(c.tables)==1 and len(c.tables[0].rows)==2
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_a_later_table_failure_does_not_publish_an_earlier_valid_prefix():
    bad = table(row(cell(properties="<w:vMerge/>") + cell()))
    c = read(source(table() + bad)[0])
    assert c.status == "blocked" and c.tables == () and len(c.issues) == 1
    assert c.issues[0].code == "invalid_vertical_merge"
    assert c.issues[0].anchor.path[:2] == (0, 1)


def test_nested_fake_body_does_not_authorize_a_table_context():
    raw, _ = source("<w:p><w:body>" + table() + "</w:body></w:p>")
    c = read(raw)
    assert c.status == "blocked" and c.issues[0].code == "unsupported_table_context"


def test_missing_limit_field_and_exact_manifest_boundary():
    import json
    from dataclasses import asdict

    raw, _ = source()
    c = read(raw)
    value = asdict(c)
    value.pop("catalog_sha256")
    size = len(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert read(raw, limits=api().TableLimits(max_manifest_bytes=size)) == c
    error(
        "table_limit_exceeded",
        lambda: read(raw, limits=api().TableLimits(max_manifest_bytes=size - 1)),
    )
    limits = api().TableLimits()
    object.__delattr__(limits, "max_cells")
    error("invalid_input", lambda: read(raw, limits=limits))
