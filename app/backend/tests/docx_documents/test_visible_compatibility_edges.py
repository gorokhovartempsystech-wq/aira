"""Fresh source authority, one selected DOM, bounds and profile separation."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_compatibility_contexts import fixture
from test_docx_note_catalog import note
from test_docx_section_catalog import reference, section
from test_docx_table_catalog import paragraph
from test_docx_visibility_styles import style
from test_docx_visible_compatibility import api, build, error, request, selected
from test_docx_visible_main import canonical, payload, rehash
from test_docx_visible_notes import p, ref

from ara.docx_analysis.visibility import StyleContextLimits
from ara.docx_analysis.visible_main import VisibleLimits


def test_whole_snapshot_and_each_mapping_batch_use_one_fresh_view_without_legacy_dom(monkeypatch):
    api()
    projector = import_module("ara.docx_analysis.compatibility_view._project")
    contexts = import_module("ara.docx_analysis.compatibility_contexts._read")
    original_tree, original_view = projector.build_tree, contexts.build_compatibility_view
    trees, views = [], []
    raw, _ = fixture(
        selected(p(ref())) + selected(section(reference("H"))),
        foot=selected(note("2", content=paragraph("Foot"))),
        header=selected(paragraph("Header")),
        styles=selected(style("A")),
        settings="",
    )

    def tree(*a, **kw):
        trees.append(a[1])
        return original_tree(*a, **kw)

    def view(*a, **kw):
        views.append(1)
        return original_view(*a, **kw)

    def forbidden(*a, **kw):
        raise AssertionError("Legacy semantic parser bypassed coherent compatibility view")

    monkeypatch.setattr(projector, "build_tree", tree)
    monkeypatch.setattr(contexts, "build_compatibility_view", view)
    for name, attr in (
        ("visibility._read", "parse"),
        ("table_styles._read", "parse"),
        ("sections._xml", "build_tree"),
        ("notes._xml", "build_tree"),
        ("visible_notes._parse", "build_tree"),
    ):
        monkeypatch.setattr(import_module("ara.docx_analysis." + name), attr, forbidden)
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Header", "Foot"]
    assert views == [1] and sorted(trees) == [
        "custom/Foot.xml",
        "custom/H.xml",
        "custom/Main.xml",
        "custom/Settings.xml",
        "custom/Styles.xml",
    ]
    for requests in ((request(s.fragments[0]),) * 50, ()):
        trees.clear()
        views.clear()
        result = api().map_compatibility_spans(raw, s, requests=requests)
        assert len(result) == len(requests) and views == [1] and len(trees) == 5


def test_raw_limits_apply_before_any_dom_even_to_discarded_payload(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM allocated before raw budgets")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    raw, _ = fixture(selected(paragraph("Text")), styles=selected(style("A") + style("B")))
    for limits in (
        VisibleLimits(max_xml_nodes=3),
        VisibleLimits(max_xml_depth=3),
        VisibleLimits(max_xml_characters=5),
        VisibleLimits(max_runs=1),
        VisibleLimits(styles=StyleContextLimits(max_styles=1)),
    ):
        # A second raw run is intentionally in a discarded branch.
        from test_docx_compatibility_catalog import alternate, choice

        body = alternate(choice("x", paragraph("Discarded")) + choice("w", paragraph("Text")))
        value = fixture(body, styles=selected(style("A") + style("B")))[0]
        error("view_limit_exceeded", lambda: build(value, limits=limits))


def test_identity_and_hash_fail_before_selected_factory(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("Semantic factory before input validation")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_contexts._read"),
        "build_compatibility_view",
        forbidden,
    )
    raw = fixture()[0]
    for args in (
        dict(document_id="bad"),
        dict(storage_revision=True),
        dict(source_sha256="X" * 64),
        dict(limits=object()),
    ):
        error("invalid_input", lambda args=args: build(raw, **args))
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))


def test_output_manifest_boundary_includes_all_compatibility_evidence():
    raw = fixture(selected(paragraph("Text")) * 30)[0]
    s = build(raw)
    maximum = len(canonical(payload(s)))
    assert build(raw, limits=VisibleLimits(max_manifest_bytes=maximum)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_manifest_bytes=maximum - 1)),
    )
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage) - 1)),
    )
    assert build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage))) == s


def test_exact_foreign_dto_shapes_and_mapping_budgets_are_rejected():
    raw = fixture(selected(paragraph("Text")))[0]
    s = build(raw)
    q = request(s.fragments[0])
    error("invalid_snapshot", lambda: api().map_compatibility_spans(raw, object(), requests=()))
    error(
        "invalid_snapshot",
        lambda: api().map_compatibility_spans(
            raw, replace(s, fragments=list(s.fragments)), requests=()
        ),
    )
    error("invalid_input", lambda: api().map_compatibility_spans(raw, s, requests=[q]))
    error(
        "invalid_input",
        lambda: api().map_compatibility_spans(raw, s, requests=(replace(q, start=True),)),
    )
    error(
        "view_limit_exceeded",
        lambda: api().map_compatibility_spans(
            raw, s, requests=(q, q), limits=VisibleLimits(max_span_requests=1)
        ),
    )
    error(
        "view_limit_exceeded",
        lambda: api().map_compatibility_spans(
            raw, s, requests=(q,), limits=VisibleLimits(max_requested_characters=3)
        ),
    )
    error(
        "view_limit_exceeded",
        lambda: api().map_compatibility_spans(
            raw, s, requests=(q, q), limits=VisibleLimits(max_mapped_slices=1)
        ),
    )


def test_selected_unresolved_used_style_still_blocks_actual_content():
    raw = fixture(
        '<w:p><w:pPr><w:pStyle w:val="A"/></w:pPr><w:r><w:t>Secret</w:t></w:r></w:p>',
        styles=selected(style("A", '<w:basedOn w:val="Missing"/>')),
    )[0]
    s = build(raw)
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    assert any(c.code == "unresolved_paragraph_style" for c in s.coverage)


def test_blocked_bundle_retains_no_ready_or_absent_metadata_authority():
    raw = fixture(paragraph("Secret"), styles=selected(style("A") + style("A")))[0]
    s = build(raw)
    assert not s.complete and s.style_context.status == "blocked"
    assert s.style_context.profile == "docx-visibility/mc-styles-context-v1"
    assert (
        s.style_context.styles == () and s.references == s.fragments == s.runs == s.paragraphs == ()
    )
    assert any(
        c.code == "duplicate_default_style" or c.code == "invalid_style_identity"
        for c in s.coverage
    )
    assert s == build(raw) and "Secret" not in repr(s)


def test_rehashed_note_target_and_old_style_profile_are_not_trusted():
    raw = fixture(selected(p(ref())), foot=selected(note("2", content=paragraph("Foot"))))[0]
    s = build(raw)
    assert s.complete and s.references
    fake_ref = replace(s.references[0], target_anchor=s.references[0].paragraph_anchor)
    fake = rehash(replace(s, references=(fake_ref,)))
    error("invalid_snapshot", lambda: api().map_compatibility_spans(raw, fake, requests=()))
    fake = rehash(
        replace(
            s, style_context=replace(s.style_context, profile="docx-visibility/styles-context-v1")
        )
    )
    error("invalid_snapshot", lambda: api().map_compatibility_spans(raw, fake, requests=()))


def test_fresh_process_import_build_and_map_only_use_given_bytes():
    raw = fixture(selected(paragraph("Fixture")), styles=selected(style("A")))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from uuid import UUID
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected I/O or XML serialization")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.visible_compatibility import (
    build_compatibility_snapshot,map_compatibility_spans,VisibleSpanRequest)
s=build_compatibility_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="Fixture"
f=s.fragments[0]
m=map_compatibility_spans(data,s,requests=(VisibleSpanRequest(f.fragment_id,0,7,"Fixture"),))
assert len(m)==1 and len(m[0].slices)==1
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        timeout=30,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_selected_gridless_vertical_merge_retains_real_origin_cell():
    from xml.etree import ElementTree as ET

    from test_docx_compatibility_catalog import MAIN
    from test_docx_grid_tables import gridless
    from test_docx_move_catalog import resolve
    from test_docx_table_catalog import cell, row
    from test_docx_visible_compatibility import assert_original

    span = selected('<w:gridSpan w:val="3"/>')
    rows = selected(row(cell(paragraph("Origin"), span + selected('<w:vMerge w:val="restart"/>'))))
    rows += selected(row(cell("<w:p/>", span + selected("<w:vMerge/>"))))
    raw, parts = fixture(selected(gridless(rows)))
    s = build(raw)
    assert s.complete and s.analysis_text == "Origin" and len(s.fragments) == 1
    assert any(c.code == "derived_table_grid" for c in s.coverage)
    assert resolve(ET.fromstring(parts[MAIN]), s.fragments[0].flow_anchor).tag.endswith("}tc")
    assert_original(raw, parts, s)


def test_repeated_visible_notes_share_target_while_hidden_and_deleted_refs_do_not_activate():
    from test_docx_visible_compatibility import assert_original
    from test_docx_visible_notes import literal

    body = "<w:p><w:r>" + literal("A") + selected(ref()) + literal("B")
    body += selected(ref()) + literal("C") + "</w:r>"
    body += "<w:r><w:rPr><w:vanish/></w:rPr>" + selected(ref("999")) + "</w:r>"
    body += '<w:del w:id="4"><w:r>' + selected(ref("998")) + "</w:r></w:del></w:p>"
    raw, parts = fixture(selected(body), foot=selected(note("2", content=paragraph("Foot"))))
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["A", "B", "C", "Foot"]
    assert len(s.references) == 2 and s.references[0].target_anchor == s.references[1].target_anchor
    assert_original(raw, parts, s)


@pytest.mark.parametrize("duplicate_active", [False, True])
def test_part_wide_note_move_identity_guard_uses_selected_definitions(duplicate_active):
    from test_docx_compatibility_catalog import alternate, choice
    from test_docx_move_catalog import group, run
    from test_docx_visible_compatibility import assert_original

    content = "<w:p>" + selected(group(content=run("Old")))
    content += selected(group("To", content=run("New"))) + "</w:p>"
    first, second = note("2", content=content), note("3", content=content)
    definitions = (
        selected(first + second)
        if duplicate_active
        else alternate(choice("x", second) + choice("w", first))
    )
    raw, parts = fixture(selected(p(ref())), foot=definitions)
    s = build(raw)
    if duplicate_active:
        assert not s.complete and s.analysis_text == "" and s.references == ()
        assert any(c.code == "move_catalog_blocked" for c in s.coverage)
    else:
        assert s.complete and s.analysis_text == "New"
        assert_original(raw, parts, s)


def test_hidden_selected_unknown_content_cannot_bypass_reader_grammar():
    body = "<w:p><w:r><w:rPr><w:vanish/></w:rPr>" + selected("<w:drawing/>") + "</w:r></w:p>"
    s = build(fixture(paragraph("Before") + body)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.runs == ()
    assert any(c.status == "blocked" for c in s.coverage)


def test_projection_text_ownership_failure_is_a_valid_atomic_snapshot():
    raw = fixture(
        "<x:unwrap>Mixed" + paragraph("Text") + "</x:unwrap>",
        attrs='mc:Ignorable="x" mc:ProcessContent="x:unwrap"',
    )[0]
    s = build(raw)
    assert not s.complete and s.analysis_text == "" and s.style_context.status == "blocked"
    assert any(c.code == "unsupported_compatibility_text_boundary" for c in s.coverage)
    assert api().map_compatibility_spans(raw, s, requests=()) == ()
