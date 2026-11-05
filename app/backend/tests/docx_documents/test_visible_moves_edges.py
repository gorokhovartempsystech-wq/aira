"""Move reader bounds, forged DTOs and independent no-I/O acceptance."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_move_catalog import group, run
from test_docx_visible_main import canonical, codes, payload, source, style
from test_docx_visible_moves import api, build, error, paired, request


def test_limits_bound_entire_main_including_excluded_source():
    raw, _ = source("<w:p>" + paired(run("ABC"), run("X" * 1000)) + "</w:p>")
    for kwargs in (
        dict(max_xml_nodes=5),
        dict(max_xml_depth=4),
        dict(max_xml_characters=500),
        dict(max_runs=1),
        dict(max_pieces=1),
        dict(max_text_characters=2),
        dict(max_coverage_items=1),
    ):
        error(
            "view_limit_exceeded",
            lambda kwargs=kwargs: build(raw, limits=api().VisibleLimits(**kwargs)),
        )
    s = build(raw)
    size = len(canonical(payload(s)))
    assert build(raw, limits=api().VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_manifest_bytes=size - 1)),
    )
    error(
        "view_limit_exceeded",
        lambda: api().map_move_spans(raw, s, requests=(), limits=api().VisibleLimits(max_runs=1)),
    )


def test_aggregate_preflight_precedes_any_semantic_main_dom(monkeypatch):
    raw, _ = source("<w:p>" + paired() + "</w:p>", style("P", "<w:rPr><w:vanish/></w:rPr>"))
    parser = import_module("ara.docx_package.projection._parse")

    def forbidden(*args, **kwargs):
        raise AssertionError("Semantic DOM precedes aggregate budget")

    monkeypatch.setattr(parser, "_BoundedBuilder", forbidden)
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_xml_nodes=2)))


def test_request_limits_and_atomic_failures():
    raw, _ = source("<w:p>" + run("A") + paired(run("BC")) + "</w:p>")
    s = build(raw)
    q = request(s.fragments[0])
    for kwargs in (
        dict(max_span_requests=1),
        dict(max_requested_characters=5),
        dict(max_mapped_slices=3),
    ):
        error(
            "view_limit_exceeded",
            lambda kwargs=kwargs: api().map_move_spans(
                raw, s, requests=(q, q), limits=api().VisibleLimits(**kwargs)
            ),
        )
    for bad, code in (
        (replace(q, quote="BAD"), "invalid_span"),
        (replace(q, end=4), "invalid_span"),
        (replace(q, fragment_id="unknown"), "unknown_fragment"),
        (replace(q, start=True), "invalid_input"),
    ):
        error(code, lambda bad=bad: api().map_move_spans(raw, s, requests=(q, bad)))
    error("invalid_input", lambda: api().map_move_spans(raw, s, requests=[q]))


def test_invalid_inputs_mutated_limits_foreign_shapes_and_frozen_records():
    raw, _ = source("<w:p>" + paired() + "</w:p>")
    for kwargs in (
        dict(storage_revision=True),
        dict(document_id="uuid"),
        dict(source_sha256="A" * 64),
        dict(limits={}),
    ):
        error("invalid_input", lambda kwargs=kwargs: build(raw, **kwargs))
    error("invalid_input", lambda: build(bytearray(raw)))
    limits = api().VisibleLimits()
    object.__setattr__(limits, "max_runs", 0)
    error("invalid_input", lambda: build(raw, limits=limits))
    s = build(raw)

    class Trap:
        def __eq__(self, other):
            raise AssertionError("foreign equality invoked")

        def __repr__(self):
            raise AssertionError("foreign repr invoked")

        def __iter__(self):
            raise AssertionError("foreign iteration invoked")

    for fake in (
        replace(s, fragments=Trap()),
        replace(s, analysis_text=Trap()),
        replace(s, profile=Trap()),
        replace(s, runs=(Trap(),)),
        replace(s, complete=1),
    ):
        error("invalid_snapshot", lambda fake=fake: api().map_move_spans(raw, fake, requests=()))
    with pytest.raises(FrozenInstanceError):
        s.analysis_text = "changed"


@pytest.mark.parametrize(
    "definition,code",
    [
        ("", "missing_character_style"),
        (style("C"), "character_style_type_mismatch"),
        (style("C", '<w:basedOn w:val="C"/>', "character"), "unresolved_character_style"),
    ],
)
def test_move_destination_does_not_bypass_style_resolution(definition, code):
    destination = '<w:r><w:rPr><w:rStyle w:val="C"/><w:vanish w:val="0"/></w:rPr><w:t>A</w:t></w:r>'
    s = build(source("<w:p>" + paired(destination) + "</w:p>", definition)[0])
    assert not s.complete and s.fragments == () and ("blocked", code) in codes(s)


def test_implicit_character_style_and_move_catalog_not_inferred_from_visibility():
    raw, _ = source(
        "<w:p>" + paired() + "</w:p>",
        style("C", '<w:rPr><w:vanish w:val="0"/></w:rPr>', "character", 'w:default="1"'),
    )
    assert ("blocked", "implicit_character_style") in codes(build(raw))
    # The source side is excluded, but a nested move inside it remains ambiguous.
    nested = paired(group("To", name="nested", identity="5"))
    raw, _ = source("<w:p>" + paired(origin=nested) + "</w:p>")
    assert ("blocked", "move_catalog_blocked") in codes(build(raw))


def test_comments_do_not_shift_original_indices():
    raw, _ = source("<w:p><!-- synthetic --><?fixture a?>" + paired(run("A")) + "</w:p>")
    s = build(raw)
    assert s.complete and s.analysis_text == "A"
    mapped = api().map_move_spans(raw, s, requests=(request(s.fragments[0]),))
    assert mapped[0].slices[0].anchor.path == (0, 0, 4, 0, 0)


def test_fresh_process_import_build_map_without_application_io():
    raw, _ = source("<w:p>" + run("A") + paired(run("BC")) + "</w:p>")
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
from ara.docx_analysis.visible_moves import build_move_snapshot,map_move_span
s=build_move_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
f=s.fragments[0]
m=map_move_span(data,s,fragment_id=f.fragment_id,start=0,end=3,quote="ABC")
assert len(m.slices)==2 and s.analysis_text=="ABC" and s.complete
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


def test_namespace_budget_is_checked_before_any_semantic_main_dom(monkeypatch):
    destination = '<w:r xmlns:unused="' + "x" * 4096 + '"><w:t>A</w:t></w:r>'
    raw, _ = source("<w:p>" + paired(destination) + "</w:p>")
    parser = import_module("ara.docx_package.projection._parse")

    def forbidden(*args, **kwargs):
        raise AssertionError("Namespace allocation precedes the move preflight")

    monkeypatch.setattr(parser, "_BoundedBuilder", forbidden)
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_xml_characters=1024)),
    )
