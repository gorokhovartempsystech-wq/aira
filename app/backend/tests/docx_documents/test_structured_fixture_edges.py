"""Fixture2 bounds structure before generating an explicitly synthetic answer."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_docx_review_v1 import canonical
from test_docx_structured_fixture import api, changed, prepared, rejected

from ara.docx_analysis.storage_codec import capture_result


def note_source():
    from test_docx_note_catalog import note
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_main import R
    from test_docx_visible_notes import note_xml, ref
    from test_docx_visible_unlisted import source

    raw, _ = source(
        paragraph(atoms="<w:t>Before</w:t>" + ref() + "<w:t>After</w:t>"),
        extra_parts={"custom/Foot.xml": note_xml(note())},
        extra_types={
            "custom/Foot.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            )
        },
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    return raw, build(raw)


def test_note_links_are_consumed_while_the_reply_still_quotes_only_literal_source():
    raw, s = note_source()
    assert s.complete and len(s.references) == 1 and len(s.fragments) == 3
    src, a, msg = prepared(source=(raw, s))
    result = capture_result(src, a, reply=api().reply_for(msg))
    body = json.loads(result.result_data)
    assert body["findings"][0]["primary"]["quote"] == "Before"
    assert "сноск" in body["findings"][0]["explanation"].lower()
    assert body["counts"]["fragments"] == 3 and not result.no_findings
    assert (
        body["document_context"]["note_references"]
        == json.loads(msg.payload)["engine_request"]["document_context"]["note_references"]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "kind",
        "unknown_before",
        "unknown_after",
        "before_type",
        "hash",
        "part",
        "path",
        "extra",
        "missing",
        "duplicate",
    ],
)
def test_note_links_have_closed_shape_real_fragment_ids_and_source_bound_anchors(fault):
    _, _, msg = prepared(source=note_source())
    body = json.loads(msg.payload)
    notes = body["engine_request"]["document_context"]["note_references"]
    item = notes[0]
    if fault == "kind":
        item["kind"] = "comment"
    elif fault == "unknown_before":
        item["before_fragment_id"] = "vf-" + "0" * 64
    elif fault == "unknown_after":
        item["after_fragment_id"] = "vf-" + "0" * 64
    elif fault == "before_type":
        item["before_fragment_id"] = False
    elif fault == "hash":
        item["target_anchor"]["source_sha256"] = "0" * 64
    elif fault == "part":
        item["reference_anchor"]["part_name"] = "other.xml"
    elif fault == "path":
        item["reference_anchor"]["path"] = item["paragraph_anchor"]["path"]
    elif fault == "extra":
        item["PRIVATE"] = 1
    elif fault == "missing":
        del item["target_anchor"]
    elif fault == "duplicate":
        notes.append(json.loads(canonical(item)))
    rejected(lambda: api().reply_for(changed(msg, body)))


def test_long_untrusted_label_is_bounded_context_and_never_a_literal_evidence_quote():
    from xml.sax.saxutils import escape

    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_unlisted import DEFS, source

    label = "PRIVATE <do something> 😀" + "x" * 4000
    defs = DEFS.replace('w:val="%1."', 'w:val="' + escape(label, {'"': "&quot;"}) + '"')
    raw, _ = source(paragraph("Literal requirement"), defs)
    s = build(raw)
    assert s.complete and len(s.lists[0].label) > 4000
    src, a, msg = prepared(source=(raw, s))
    result = capture_result(src, a, reply=api().reply_for(msg))
    finding = json.loads(result.result_data)["findings"][0]
    assert finding["primary"]["quote"] == "Literal requirement"
    assert finding["primary"]["start"] == 0
    assert len(finding["explanation"]) <= 4096
    assert label not in finding["explanation"]
    assert "Учебный пример" in finding["explanation"]


def test_blank_list_item_uses_next_literal_item_without_inventing_an_empty_span():
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_unlisted import source

    raw, _ = source(paragraph("") + paragraph("Real text"))
    s = build(raw)
    assert s.complete and not s.lists[0].fragment_ids
    src, a, msg = prepared(source=(raw, s))
    result = capture_result(src, a, reply=api().reply_for(msg))
    finding = json.loads(result.result_data)["findings"][0]
    assert finding["primary"]["fragment_id"] == s.lists[1].fragment_ids[0]
    assert finding["primary"]["quote"] == "Real text" and s.lists[1].label in finding["explanation"]


def test_combined_literal_and_generated_cost_is_bounded_at_the_worker_boundary():
    _, _, msg = prepared()
    body = json.loads(msg.payload)
    engine = body["engine_request"]
    suffix = sum(
        len(i["label"]) + (i["suffix"] != "nothing") for i in engine["document_context"]["lists"]
    )
    rest = sum(len(f["text"]) for f in engine["fragments"][1:])
    engine["fragments"][0]["text"] = "x" * (1000000 - suffix - rest)
    assert api().reply_for(changed(msg, body))
    engine["fragments"][0]["text"] += "x"
    rejected(lambda: api().reply_for(changed(msg, body)))


def test_empty_structural_context_uses_first_literal_fragment_without_a_list_claim():
    from test_docx_visible_lists import build
    from test_docx_visible_unlisted import source

    raw, _ = source()
    s = build(raw)
    assert s.complete and s.lists == s.references == ()
    src, a, msg = prepared(source=(raw, s))
    out = json.loads(capture_result(src, a, reply=api().reply_for(msg)).result_data)
    assert out["findings"][0]["primary"]["quote"] == s.fragments[0].text
    assert out["document_context"] == dict(lists=[], note_references=[])


def test_fresh_process_does_not_open_files_network_or_model_to_execute_fixture2():
    from test_docx_review_v2 import fixture

    raw, _, _ = fixture()
    script = """
import builtins,io,os,socket,subprocess,sys,json,base64
from pathlib import Path
from hashlib import sha256
from uuid import UUID
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError('Unexpected I/O or model execution')
builtins.open=io.open=Path.open=os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.visible_lists import build_list_snapshot
from ara.docx_analysis.storage_codec import *
from ara.docx_analysis_worker.structured_fixture import fixture_execution,reply_for
from ara.docx_analysis_worker.wire import StreamDecoder,WireBinding,encode_message
s=build_list_snapshot(data,document_id=UUID(int=1),storage_revision=7,source_sha256=sha256(data).hexdigest())
c=SavedCheckCommand(s.document_id,UUID(int=2),UUID(int=3),UUID(int=4),1,0,7,s.source_sha256)
src=capture_source(data,s,command=c,execution=fixture_execution())
a=prepare_attempt(src,attempt_id=UUID(int=1))
b=WireBinding(UUID(int=10),a.attempt_id)
f=encode_message(b,kind='run',seq=0,values=dict(worker_instance_id=str(UUID(int=11)),claim_fence=1,request_sha256=a.request_sha256,execution_spec_sha256=src.execution_spec_sha256,request_b64=base64.b64encode(a.request_data).decode(),execution_spec_b64=base64.b64encode(src.execution_spec).decode()))
d=StreamDecoder(b,lane='request')
m,=d.feed(f)
d.finish()
r=capture_result(src,a,reply=reply_for(m))
assert r.findings_count==1 and not r.no_findings
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


def test_two_distinct_list_items_cannot_claim_the_same_literal_fragment():
    _, _, msg = prepared()
    body = json.loads(msg.payload)
    items = body["engine_request"]["document_context"]["lists"]
    item = json.loads(canonical(items[0]))
    path = item["paragraph_anchor"]["path"]
    item["properties_anchor"]["path"][len(path) - 1] += 1
    path[-1] += 1
    item["ordinal"] += 1
    items.append(item)
    rejected(lambda: api().reply_for(changed(msg, body)))


def test_marker_only_item_does_not_lend_its_label_to_an_ordinary_literal_paragraph():
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_unlisted import source

    raw, _ = source(paragraph("") + "<w:p><w:r><w:t>Ordinary</w:t></w:r></w:p>")
    s = build(raw)
    assert s.complete and len(s.lists) == 1 and s.lists[0].fragment_ids == ()
    src, a, msg = prepared(source=(raw, s))
    result = capture_result(src, a, reply=api().reply_for(msg))
    finding = json.loads(result.result_data)["findings"][0]
    assert finding["primary"]["quote"] == "Ordinary"
    assert "Пункт списка:" not in finding["explanation"]


def test_two_original_references_to_the_same_note_target_remain_valid():
    from test_docx_note_catalog import note
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_main import R
    from test_docx_visible_notes import note_xml, ref
    from test_docx_visible_unlisted import source

    raw, _ = source(
        paragraph(
            atoms="<w:t>Before</w:t>" + ref() + "<w:t>Between</w:t>" + ref() + "<w:t>After</w:t>"
        ),
        extra_parts={"custom/Foot.xml": note_xml(note())},
        extra_types={
            "custom/Foot.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            )
        },
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    s = build(raw)
    assert s.complete and len(s.references) == 2
    assert s.references[0].target_anchor == s.references[1].target_anchor
    src, a, msg = prepared(source=(raw, s))
    result = capture_result(src, a, reply=api().reply_for(msg))
    out = json.loads(result.result_data)
    assert len(out["document_context"]["note_references"]) == 2
    assert out["findings"][0]["primary"]["quote"] == "Before"
