"""Visibility admission, resource accounting and hostile foreign DTO boundaries."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from uuid import UUID

import pytest
from test_docx_visible_main import GAP, build, codes, error, request, source, style

from ara.docx_analysis import visible_main as api
from ara.docx_analysis.visibility import StyleContextError, StyleContextLimits
from ara.docx_package import DocxError


def test_smaller_call_limits_report_limits_not_corrupt_snapshot():
    raw, _ = source(styles=style("A") + style("B"))
    s = build(raw)
    for limits in (
        api.VisibleLimits(max_runs=2),
        api.VisibleLimits(max_text_characters=3),
        api.VisibleLimits(max_xml_nodes=3),
    ):
        error(
            "view_limit_exceeded", lambda: api.map_visible_spans(raw, s, requests=(), limits=limits)
        )
    with pytest.raises(StyleContextError) as caught:
        api.map_visible_spans(
            raw, s, requests=(), limits=api.VisibleLimits(styles=StyleContextLimits(max_styles=1))
        )
    assert caught.value.code == "style_limit_exceeded"


def test_foreign_values_never_invoke_hooks_or_leak_details():
    class Trap:
        def __repr__(self):
            raise AssertionError("repr called")

        def __eq__(self, other):
            raise AssertionError("eq called")

        def __iter__(self):
            raise AssertionError("iter called")

    raw, _ = source()
    s = build(raw)
    for value in (
        replace(s, fragments=Trap()),
        replace(s, analysis_text=Trap()),
        replace(s, runs=(replace(s.runs[0], direct_properties=Trap()),)),
    ):
        error("invalid_snapshot", lambda: api.map_visible_spans(raw, value, requests=()))
    with pytest.raises(FrozenInstanceError):
        s.analysis_text = "changed"


@pytest.mark.parametrize(
    "selector,styles,code",
    [
        ("missing", "", "missing_character_style"),
        ("C", style("C"), "character_style_type_mismatch"),
        ("C", style("C", '<w:basedOn w:val="C"/>', "character"), "unresolved_character_style"),
    ],
)
def test_character_errors_not_bypassed_by_direct_false(selector, styles, code):
    body = (
        f'<w:p><w:r><w:rPr><w:rStyle w:val="{selector}"/>'
        '<w:vanish w:val="0"/></w:rPr><w:t>x</w:t></w:r></w:p>'
    )
    s = build(source(body, styles)[0])
    assert ("blocked", code) in codes(s)


def test_empty_default_character_and_false_boundary_are_admitted():
    styles = style("C", kind="character", attrs='w:default="1"')
    styles += style("P", '<w:rPr><w:vanish w:val="0"/></w:rPr>', attrs='w:default="1"')
    body = (
        '<w:p><w:pPr><w:rPr><w:vanish w:val="0"/>'
        '<w:specVanish w:val="0"/><w:webHidden/></w:rPr></w:pPr>'
        "<w:r><w:t>text</w:t></w:r></w:p>"
    )
    s = build(source(body, styles)[0])
    assert s.complete and s.analysis_text == "text"
    assert s.paragraphs[0].mark_properties.web_hidden.value is True
    assert s.runs[0].direct_properties.vanish.value is None


def test_global_catalog_precedes_grammar_and_implicit_precedes_boundary():
    styles = style("A") + style("A")
    s = build(source("<w:tbl/>", styles)[0])
    assert ("blocked", "style_context_blocked") in codes(s)
    assert ("blocked", "style_usage_unproven") in codes(s)
    styles = style("C", '<w:rPr><w:vanish w:val="0"/></w:rPr>', "character", 'w:default="1"')
    styles += (
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>"
    )
    assert ("blocked", "implicit_character_style") in codes(build(source(styles=styles)[0]))


def test_hyperlinks_ins_and_nested_link_rejection():
    body = (
        '<w:p><w:hyperlink w:anchor="Here"><w:ins w:id="1">'
        "<w:r><w:t>Link</w:t></w:r></w:ins></w:hyperlink></w:p>"
    )
    raw, _ = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "Link"
    assert api.map_visible_spans(raw, s, requests=(request(s.fragments[0]),))[0].slices[
        0
    ].anchor.path == (0, 0, 0, 0, 0, 0)
    nested = body.replace("<w:r>", '<w:hyperlink w:anchor="Other"><w:r>').replace(
        "</w:r>", "</w:r></w:hyperlink>"
    )
    assert ("blocked", "unsupported_main_flow") in codes(build(source(nested)[0]))


def test_all_hidden_and_empty_batches_still_authenticate_source():
    raw, _ = source("<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>SECRET</w:t></w:r></w:p>")
    s = build(raw)
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert api.map_visible_spans(raw, s, requests=()) == ()
    with pytest.raises(DocxError):
        build(b"not a package")
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))


def test_nested_limits_are_revalidated():
    raw, _ = source()
    limits = api.VisibleLimits()
    object.__setattr__(limits.styles, "max_depth", False)
    error("invalid_input", lambda: build(raw, limits=limits))


def test_incomplete_exact_uuid_and_limit_objects_fail_with_static_errors():
    raw, _ = source()
    error("invalid_input", lambda: build(raw, document_id=object.__new__(UUID)))
    error("invalid_input", lambda: build(raw, limits=object.__new__(api.VisibleLimits)))
    nested = object.__new__(StyleContextLimits)
    error("invalid_input", lambda: api.VisibleLimits(styles=nested))


def test_large_batch_disjoint_atoms_and_global_output_budget():
    body = "<w:p>" + "<w:r><w:t>x</w:t></w:r>" * 1000 + "</w:p>"
    raw, _ = source(body)
    s = build(raw)
    f = s.fragments[0]
    requests = tuple(api.VisibleSpanRequest(f.fragment_id, i, i + 1, "x") for i in range(1000))
    result = api.map_visible_spans(
        raw, s, requests=requests, limits=api.VisibleLimits(max_mapped_slices=1000)
    )
    assert len(result) == 1000 and all(len(m.slices) == 1 for m in result)
    assert result[-1].slices[0].anchor.path == (0, 0, 999, 0)
    error(
        "view_limit_exceeded",
        lambda: api.map_visible_spans(
            raw, s, requests=requests, limits=api.VisibleLimits(max_mapped_slices=999)
        ),
    )


def test_excluded_branches_count_toward_input_limits():
    for body in (
        '<w:p><w:del w:id="1"><w:r/><w:r/></w:del></w:p>',
        '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr><w:r/><w:r/></w:pPr></w:pPrChange></w:pPr></w:p>',
    ):
        raw, _ = source(body)
        error("view_limit_exceeded", lambda: build(raw, limits=api.VisibleLimits(max_runs=1)))
    raw, _ = source(GAP + "<w:p/>")
    error("view_limit_exceeded", lambda: build(raw, limits=api.VisibleLimits(max_paragraphs=1)))


def test_fresh_process_build_and_batch_mapping_without_application_io():
    raw, _ = source()
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
from ara.docx_analysis.visible_main import build_visible_snapshot,map_visible_span
s=build_visible_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
f=s.fragments[0]
m=map_visible_span(data,s,fragment_id=f.fragment_id,start=1,end=3,quote="bc")
assert len(m.slices)==2 and s.analysis_text=="abcd"
assert "SECRET" not in repr(s)+repr(f)+repr(m)
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
