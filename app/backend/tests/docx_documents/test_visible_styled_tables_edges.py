"""Authoritative rebuild, profile boundaries and whole-source caps for styles."""

import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_visible_styled_tables import (
    api,
    build,
    cell,
    codes,
    error,
    paragraph,
    request,
    row,
    source,
    styled_table,
    table,
    table_style,
)


def test_one_fresh_context_and_each_catalog_per_batch_including_empty(monkeypatch):
    raw = source(styled_table(), table_style())[0]
    s = build(raw)
    modules = [
        ("ara.docx_analysis.visible_main._build", "read_style_context"),
        ("ara.docx_analysis.tables", "read_table_catalog"),
        ("ara.docx_analysis.moves", "read_move_catalog"),
        ("ara.docx_analysis.table_styles._read", "catalog"),
    ]
    counts = [0] * len(modules)
    for index, (module_name, attr) in enumerate(modules):
        module = import_module(module_name)
        original = getattr(module, attr)

        def counted(*args, _index=index, _original=original, **kwargs):
            counts[_index] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, attr, counted)
    queries = (request(s.fragments[0]),) * 20
    mapped = api().map_styled_table_spans(raw, s, requests=queries)
    assert len(mapped) == 20 and all(m == mapped[0] for m in mapped)
    assert counts == [1, 1, 1, 1]
    assert api().map_styled_table_spans(raw, s, requests=()) == ()
    assert counts == [2, 2, 2, 2]


@pytest.mark.parametrize("what", ["namespace", "style_count", "style_depth", "regions"])
def test_style_preflight_runs_before_semantic_style_dom(monkeypatch, what):
    module = import_module("ara.docx_analysis.visibility._parse")

    def forbidden(*args, **kwargs):
        raise AssertionError("Style DOM before complete style budgets")

    monkeypatch.setattr(module, "Builder", forbidden)
    styles_api = import_module("ara.docx_analysis.visibility")
    kwargs = {}
    if what == "namespace":
        definitions = table_style(content='<w:rPr xmlns:big="' + "x" * 4096 + '"/>')
        kwargs = dict(max_xml_characters=1024)
    elif what == "style_count":
        definitions = table_style() + table_style("Second")
        kwargs = dict(styles=styles_api.StyleContextLimits(max_styles=1))
    elif what == "style_depth":
        definitions = table_style(
            content='<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr></w:tblStylePr>'
        )
        kwargs = dict(styles=styles_api.StyleContextLimits(max_depth=3))
    else:
        definitions = table_style(content='<w:tblStylePr w:type="firstRow"/>' * 16385)
    raw = source(styled_table(), definitions)[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(**kwargs)))


def test_proof_chain_depth_and_issues_respect_nested_style_limits():
    styles_api = import_module("ara.docx_analysis.visibility")
    definitions = table_style("Base") + table_style(content='<w:basedOn w:val="Base"/>')
    raw = source(styled_table(), definitions)[0]
    error(
        "view_limit_exceeded",
        lambda: build(
            raw, limits=api().VisibleLimits(styles=styles_api.StyleContextLimits(max_chain_depth=1))
        ),
    )
    raw = source(styled_table(), table_style(content="<w:unknown/>"))[0]
    error(
        "view_limit_exceeded",
        lambda: build(
            raw, limits=api().VisibleLimits(styles=styles_api.StyleContextLimits(max_issues=1))
        ),
    )


def test_manifest_requests_and_slices_limits_still_apply():
    raw = source(styled_table(), table_style())[0]
    s = build(raw)
    error(
        "view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=1))
    )
    requests = (request(s.fragments[0]),) * 2
    for values in (
        dict(max_span_requests=1),
        dict(max_requested_characters=1),
        dict(max_mapped_slices=1),
    ):
        error(
            "view_limit_exceeded",
            lambda values=values: api().map_styled_table_spans(
                raw, s, requests=requests, limits=api().VisibleLimits(**values)
            ),
        )
    error("invalid_input", lambda: api().map_styled_table_spans(raw, s, requests=[]))


def test_merged_origins_and_comments_revisions_keep_previous_rules():
    p = '<w:p><w:r><w:t>A</w:t></w:r><w:del w:id="1"><w:r><w:delText>OLD</w:delText>'
    p += '</w:r></w:del><w:ins w:id="2"><w:r><w:t>B</w:t></w:r></w:ins>'
    p += '<w:commentRangeStart w:id="3"/><w:commentRangeEnd w:id="3"/></w:p>'
    rows = row(cell(p, '<w:vMerge w:val="restart"/>')) + row(cell("<w:p/>", "<w:vMerge/>"))
    raw = source(table(rows, 1), table_style(default=True))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "AB" and len(s.fragments) == 1
    assert {
        ("excluded", "merged_cell_continuation"),
        ("excluded", "deleted_content"),
        ("excluded", "comments_policy"),
    } <= codes(s)
    bad = source(
        table(
            row(cell(p, '<w:vMerge w:val="restart"/>'))
            + row(cell(paragraph("Hidden content"), "<w:vMerge/>")),
            1,
        ),
        table_style(default=True),
    )[0]
    s = build(bad)
    assert not s.complete and s.fragments == ()
    assert ("blocked", "unresolved_merged_cell_content") in codes(s)


def test_default_table_style_without_tables_never_requires_table_proof(monkeypatch):
    module = import_module("ara.docx_analysis.table_styles._read")

    def forbidden(*args, **kwargs):
        raise AssertionError("Unapplied table-style proof")

    monkeypatch.setattr(module, "catalog", forbidden)
    raw = source(paragraph("Body"), table_style(content="<w:unknown/>", default=True))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Body"


def test_global_style_ambiguity_and_unsupported_table_revisions_still_block():
    s = build(source(styled_table(), table_style() + table_style())[0])
    assert not s.complete and s.fragments == () and ("blocked", "style_context_blocked") in codes(s)
    body = table(
        properties='<w:tblStyle w:val="T"/><w:tblPrChange w:id="1"><w:tblPr/></w:tblPrChange>'
    )
    s = build(source(body, table_style())[0])
    assert not s.complete and s.fragments == () and ("blocked", "table_catalog_blocked") in codes(s)


def test_factory_and_mapper_have_no_application_io_in_fresh_process():
    raw = source(styled_table(), table_style())[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
from uuid import UUID
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.visible_styled_tables import (
    build_styled_table_snapshot,map_styled_table_spans,VisibleSpanRequest,
)
s=build_styled_table_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Cell"
f=s.fragments[0]
m=map_styled_table_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,4,"Cell"),))
assert len(m)==1 and len(m[0].slices)==1
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


def test_neutral_style_never_bypasses_hidden_row_or_implicit_character_guard():
    hidden_row = table(row(cell(paragraph("Row")), properties="<w:hidden/>"), 1)
    s = build(source(hidden_row, table_style(content="<w:hidden/>", default=True))[0])
    assert not s.complete and s.fragments == ()
    assert ("blocked", "unresolved_hidden_row") in codes(s)
    from test_docx_visible_main import style

    definitions = table_style() + style(
        "Implicit",
        '<w:rPr><w:vanish w:val="false"/></w:rPr>',
        kind="character",
        attrs='w:default="true"',
    )
    s = build(source(styled_table(), definitions)[0])
    assert not s.complete and s.fragments == ()
    assert ("blocked", "implicit_character_style") in codes(s)


def test_repeated_quotes_in_separately_styled_tables_do_not_share_source_slices():
    raw = source(
        styled_table("Same", "T") + paragraph("Gap") + styled_table("Same", "U"),
        table_style("T") + table_style("U"),
    )[0]
    s = build(raw)
    assert s.complete
    first, _, second = s.fragments
    assert first.text == second.text and first.fragment_id != second.fragment_id
    result = api().map_styled_table_spans(raw, s, requests=(request(second), request(first)))
    assert result[0].slices[0].anchor.path[:2] == (0, 2)
    assert result[1].slices[0].anchor.path[:2] == (0, 0)
