"""List evidence remains bounded, source-bound and isolated from old profile admission."""

import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_note_catalog import note
from test_docx_section_catalog import reference, section
from test_docx_visible_lists import api, build, error, original, paragraph
from test_docx_visible_main import R, W, canonical, codes, payload, rehash, style
from test_docx_visible_notes import ref
from test_docx_visible_plain_controls import run
from test_docx_visible_unlisted import DEFS, LEVEL, NUMPR, source

from ara.docx_analysis.visible_main import VisibleLimits


def test_mapping_rebuilds_one_source_for_many_requests_and_an_empty_batch(monkeypatch):
    api()
    mod = import_module("ara.docx_analysis.compatibility_contexts._read")
    old, calls = mod.build_compatibility_view, []

    def counted(*a, **kw):
        calls.append(1)
        return old(*a, **kw)

    monkeypatch.setattr(mod, "build_compatibility_view", counted)
    raw, _ = source(paragraph("Literal"))
    s = build(raw)
    assert s.complete and calls == [1]
    f = s.fragments[0]
    request = api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)
    for requests in ((request,) * 40, ()):
        calls.clear()
        assert len(api().map_list_spans(raw, s, requests=requests)) == len(requests)
        assert calls == [1]


def test_incomplete_source_profile_and_shape_never_expose_forged_list_data():
    raw, _ = source(
        paragraph("Private"),
        styles=style("Normal", "<w:pPr>" + NUMPR + "</w:pPr>", attrs='w:default="1"'),
    )
    s = build(raw)
    assert type(s) is api().ListSnapshot and not s.complete and s.lists == s.fragments == ()
    raw, _ = source(paragraph("Literal"))
    s = build(raw)
    for fake in (
        replace(s, lists=[]),
        replace(s, lists=(replace(s.lists[0], ordinal=True),)),
        replace(s, lists=(replace(s.lists[0], fragment_ids=[]),)),
    ):
        error("invalid_snapshot", lambda fake=fake: api().map_list_spans(raw, fake, requests=()))
    fake = rehash(
        replace(s, lists=(replace(s.lists[0], properties_anchor=s.lists[0].definition_anchor),))
    )
    error("invalid_snapshot", lambda: api().map_list_spans(raw, fake, requests=()))
    f = s.fragments[0]
    error(
        "invalid_span",
        lambda: api().map_list_spans(
            raw, s, requests=(api().VisibleSpanRequest(f.fragment_id, 0, 2, "1."),)
        ),
    )


def test_exact_generated_text_and_manifest_coverage_budgets():
    raw, _ = source(paragraph("Text"))
    s = build(raw)
    cost = len(s.analysis_text) + sum(len(x.label) + (x.suffix != "nothing") for x in s.lists)
    assert build(raw, limits=VisibleLimits(max_text_characters=cost)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_text_characters=cost - 1)),
    )
    size = len(canonical(payload(s)))
    assert build(raw, limits=VisibleLimits(max_manifest_bytes=size)) == s
    error(
        "view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_manifest_bytes=size - 1))
    )
    assert build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage))) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_coverage_items=len(s.coverage) - 1)),
    )


def test_large_label_is_bounded_before_multiplying_it_over_many_paragraphs():
    definitions = DEFS.replace('w:val="%1."', 'w:val="' + "X" * 4097 + '"')
    error("view_limit_exceeded", lambda: build(source(paragraph("Text"), definitions)[0]))
    definitions = DEFS.replace('w:val="%1."', 'w:val="' + "X" * 4096 + '"')
    s = build(source(paragraph("Text"), definitions)[0])
    assert s.complete and len(s.lists[0].label) == 4096


def test_raw_numbering_limits_apply_before_first_semantic_tree(monkeypatch):
    api()

    def forbidden(*a, **kw):
        raise AssertionError("DOM before raw numbering bounds")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.visible_unlisted._numbering"), "build_tree", forbidden
    )
    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_view._project"), "build_tree", forbidden
    )
    raw, _ = source(paragraph("A"), DEFS.replace('w:val="%1."', 'w:val="' + "X" * 3000 + '"'))
    error("view_limit_exceeded", lambda: build(raw, limits=VisibleLimits(max_xml_characters=1000)))


def test_an_unlinked_definition_cannot_authorize_a_direct_active_list():
    s = build(source(paragraph("Private"), links=[])[0])
    assert not s.complete and s.fragments == s.lists == ()
    assert ("excluded", "unused_numbering_definition") not in codes(s)


@pytest.mark.parametrize("kind", ["header", "footnote"])
def test_numbering_in_other_active_stories_is_an_explicit_gate(kind):
    name = "H.xml" if kind == "header" else "Foot.xml"
    element = "hdr" if kind == "header" else "footnotes"
    contents = paragraph("Private") if kind == "header" else note("2", content=paragraph("Private"))
    root = ("<w:" + element + ' xmlns:w="' + W + '">' + contents + "</w:" + element + ">").encode()
    body = (
        "<w:p>" + run("Main") + "</w:p>" + section(reference("H"))
        if kind == "header"
        else "<w:p>" + run(atoms="<w:t>Main</w:t>" + ref()) + "</w:p>"
    )
    links = [
        {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
        {
            "Id": "H" if kind == "header" else "Foot",
            "Type": R + ("header" if kind == "header" else "footnotes"),
            "Target": name,
        },
    ]
    raw, _ = source(
        body,
        extra_parts={"custom/" + name: root},
        extra_types={
            "custom/" + name: "application/vnd.openxmlformats-officedocument.wordprocessingml."
            + ("header" if kind == "header" else "footnotes")
            + "+xml"
        },
        links=links,
    )
    s = build(raw)
    assert not s.complete and s.fragments == s.lists == s.references == ()


def test_note_reference_splits_one_list_item_into_exact_literal_fragments():
    foot = (
        '<w:footnotes xmlns:w="'
        + W
        + '">'
        + note("2", content="<w:p>" + run("Note") + "</w:p>")
        + "</w:footnotes>"
    ).encode()
    raw, parts = source(
        paragraph(atoms="<w:t>Before</w:t>" + ref() + "<w:t>After</w:t>"),
        extra_parts={"custom/Foot.xml": foot},
        extra_types={
            "custom/Foot.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            )
        },
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "Foot", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Before", "After", "Note"]
    assert len(s.lists) == 1 and len(s.references) == 1
    assert s.lists[0].fragment_ids == tuple(f.fragment_id for f in s.fragments[:2])
    original(raw, parts, s)


def test_ordinal_overflow_fails_atomically_and_unused_complex_definitions_stay_unactivated():
    definitions = DEFS.replace('<w:start w:val="1"/>', '<w:start w:val="2147483647"/>')
    assert build(source(paragraph("Last"), definitions)[0]).complete
    s = build(source(paragraph("Last") + paragraph("Overflow"), definitions)[0])
    assert not s.complete and s.fragments == s.lists == ()
    definitions = DEFS.replace(LEVEL, LEVEL.replace("decimal", "upperRoman"))
    s = build(source("<w:p>" + run("Unlisted") + "</w:p>", definitions)[0])
    assert s.complete and s.lists == ()
    assert ("excluded", "unused_numbering_definition") in codes(s)


def test_inert_fresh_process_preserves_source_and_does_not_import_application_services():
    raw, _ = source(paragraph("Literal"))
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from uuid import UUID
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError('Unexpected I/O or serialization')
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.visible_lists import build_list_snapshot,map_list_spans
s=build_list_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=='Literal' and s.lists[0].label=='1.'
assert map_list_spans(data,s,requests=())==()
blocked={'psycopg','sqlalchemy','onnxruntime','numpy','aira_ml','fastapi','PIL'}
assert not any(n.split('.')[0] in blocked for n in sys.modules)
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


def test_marker_only_document_keeps_list_evidence_without_fake_literal_fragments():
    raw, parts = source(paragraph("") + paragraph(""))
    s = build(raw)
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert [item.label for item in s.lists] == ["1.", "2."]
    assert all(item.fragment_ids == () for item in s.lists)
    assert api().map_list_spans(raw, s, requests=()) == ()
    original(raw, parts, s)


def test_early_selected_context_failure_still_returns_exact_list_snapshot():
    from test_docx_visible_lists import PROFILE

    body = (
        '<w:p xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:x="urn:future" mc:MustUnderstand="x">' + run("Private") + "</w:p>"
    )
    s = build(source(body)[0])
    assert type(s) is api().ListSnapshot and s.profile == PROFILE
    assert not s.complete and s.fragments == s.lists == s.references == ()
    assert s.style_context.profile == "docx-visibility/mc-pagination-styles-v1"


def test_non_list_tail_cannot_evade_the_combined_generated_text_budget():
    raw, _ = source(paragraph("A") + "<w:p>" + run("Tail") + "</w:p>")
    s = build(raw)
    assert s.complete and s.analysis_text == "A\n\nTail"
    cost = len(s.analysis_text) + len(s.lists[0].label) + 1
    assert build(raw, limits=VisibleLimits(max_text_characters=cost)) == s
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=VisibleLimits(max_text_characters=cost - 1)),
    )


def test_substitution_expansion_is_bounded_at_each_new_ordinal():
    definitions = DEFS.replace('<w:start w:val="1"/>', '<w:start w:val="9"/>')
    definitions = definitions.replace('w:val="%1."', 'w:val="' + "%1" * 4096 + '"')
    s = build(source(paragraph("Nine"), definitions)[0])
    assert s.complete and s.lists[0].label == "9" * 4096
    error(
        "view_limit_exceeded",
        lambda: build(source(paragraph("Nine") + paragraph("Ten"), definitions)[0]),
    )


def test_fields_spanning_only_non_list_paragraphs_do_not_disable_a_later_list():
    from test_docx_visible_fields import char, instr

    body = (
        "<w:p>"
        + run(atoms=char("begin") + instr("PRIVATE"))
        + "</w:p>"
        + "<w:p>"
        + run(atoms=char("separate") + "<w:t>Result</w:t>" + char("end"))
        + "</w:p>"
        + paragraph("Item")
    )
    raw, parts = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "Result\n\nItem"
    assert len(s.lists) == 1 and s.lists[0].label == "1."
    original(raw, parts, s)


def test_rehashed_incomplete_snapshot_cannot_carry_invented_list_evidence():
    good = build(source(paragraph("Good"))[0])
    raw, _ = source(paragraph("Private", number=88))
    bad = build(raw)
    assert not bad.complete and bad.lists == ()
    fake = rehash(replace(bad, lists=(replace(good.lists[0], fragment_ids=()),)))
    error("invalid_snapshot", lambda: api().map_list_spans(raw, fake, requests=()))


def test_number_removal_and_different_list_instances_do_not_restart_an_earlier_instance():
    body = paragraph("One") + paragraph("Unlisted", number=0, level=None) + paragraph("Two")
    s = build(source(body)[0])
    assert s.complete and [x.label for x in s.lists] == ["1.", "2."]
    assert ("metadata", "numbering_removed") in codes(s)


def test_explicit_false_visibility_on_numbering_label_remains_outside_active_subset():
    definitions = DEFS.replace("</w:lvl>", '<w:rPr><w:vanish w:val="0"/></w:rPr></w:lvl>')
    s = build(source(paragraph("Private"), definitions)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.lists == ()
