"""Context and source rebuilding remain bounded at the new review protocol boundary."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_review_v1 import issue, provenance, reply
from test_docx_review_v2 import api, context, fixture, prepare, rejected, validate


def test_one_fresh_source_batch_for_prepare_many_findings_and_empty_reply(monkeypatch):
    api()
    raw, _, s = fixture()
    mod = import_module("ara.docx_analysis.compatibility_contexts._read")
    old, calls = mod.build_compatibility_view, []

    def counted(*a, **kw):
        calls.append(1)
        return old(*a, **kw)

    monkeypatch.setattr(mod, "build_compatibility_view", counted)
    req = prepare(raw, s)
    assert calls == [1]
    for issues in (
        [],
        [issue(s, id="iss-" + str(i).zfill(10), explanation="Reason " + str(i)) for i in range(15)],
    ):
        calls.clear()
        result = validate(raw, s, reply(s, issues=issues), request=req)
        assert calls == [1] and result.findings_count == len(issues)
        assert json.loads(result.wire_json)["document_context"] == context(s)


def test_context_is_included_in_exact_request_and_result_byte_limits():
    raw, _, s = fixture()
    request = prepare(raw, s)
    result = validate(raw, s, request=request)
    assert (
        prepare(raw, s, limits=api().ReviewLimits(max_wire_bytes=len(request.wire_json))) == request
    )
    rejected(
        "review_limit_exceeded",
        lambda: prepare(
            raw, s, limits=api().ReviewLimits(max_wire_bytes=len(request.wire_json) - 1)
        ),
    )
    size = max(len(request.wire_json), len(result.wire_json))
    assert (
        validate(raw, s, request=request, limits=api().ReviewLimits(max_wire_bytes=size)) == result
    )
    rejected(
        "review_limit_exceeded",
        lambda: validate(
            raw,
            s,
            request=request,
            limits=api().ReviewLimits(max_wire_bytes=len(result.wire_json) - 1),
        ),
    )


@pytest.mark.parametrize(
    "raw_reply",
    [
        b'{"engine":"0.1.0","engine":"0.1.0"}',
        b'{"seconds":NaN}',
        b'{"seconds":Infinity}',
        b"not JSON",
    ],
)
def test_invalid_json_reply_is_rejected_before_source_rebuild(monkeypatch, raw_reply):
    api()
    raw, _, s = fixture()
    request = prepare(raw, s)

    def forbidden(*a, **kw):
        raise AssertionError("Source rebuild before invalid JSON is rejected")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_contexts._read"),
        "build_compatibility_view",
        forbidden,
    )
    rejected(
        "invalid_reply",
        lambda: api().validate_structured_reply(
            raw, s, provenance=provenance(), request=request, reply=raw_reply
        ),
    )


def test_context_has_note_links_and_all_literal_segments_of_a_list_in_a_table():
    from test_docx_note_catalog import note
    from test_docx_table_catalog import cell, row, table
    from test_docx_visible_inline_images import IMAGE, drawing, png
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_main import R, W
    from test_docx_visible_notes import ref
    from test_docx_visible_plain_controls import run
    from test_docx_visible_unlisted import source

    foot = (
        '<w:footnotes xmlns:w="'
        + W
        + '">'
        + note("2", content="<w:p>" + run("Note") + "</w:p>")
        + "</w:footnotes>"
    ).encode()
    body = table(
        row(
            cell(
                paragraph(
                    atoms="<w:t>Before</w:t>"
                    + drawing()
                    + "<w:t>After</w:t>"
                    + ref()
                    + "<w:t>Tail</w:t>"
                )
            )
        ),
        1,
    )
    raw, _ = source(
        body,
        extra_parts={IMAGE: png(), "custom/Foot.xml": foot},
        extra_types={
            IMAGE: "image/png",
            "custom/Foot.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            ),
        },
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "I", "Type": R + "image", "Target": "picture.bin"},
            {"Id": "Foot", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    s = build(raw)
    assert s.complete
    request = prepare(raw, s)
    engine = json.loads(request.engine_request_json)
    assert [f["text"] for f in engine["fragments"]] == ["Before", "After", "Tail", "Note"]
    assert engine["document_context"] == context(s)
    assert len(engine["document_context"]["note_references"]) == 1
    assert engine["document_context"]["lists"][0]["fragment_ids"] == [
        f.fragment_id for f in s.fragments[:3]
    ]


def test_related_literal_span_and_deduplicated_question_preserve_structured_context():
    raw, _, s = fixture()
    relation = dict(
        fragment_id=s.fragments[1].fragment_id, quote=s.fragments[1].text, status="active"
    )
    issues = [
        issue(s, type="contradiction", related=relation),
        issue(s, id="iss-9999999999", explanation="Second reason"),
    ]
    result = validate(raw, s, reply(s, issues=issues))
    out = json.loads(result.wire_json)
    assert result.findings_count == 2 and result.questions_count == 1
    assert len(out["questions"][0]["finding_ids"]) == 2
    assert out["findings"][0]["related"]["quote"] == "Other 😀"
    assert out["document_context"] == context(s)


def test_wrong_checked_count_and_provenance_never_publish_a_result():
    raw, _, s = fixture()
    rejected(
        "invalid_reply",
        lambda: validate(raw, s, reply(s, checked=dict(fragments=1, active=1, skipped_status=0))),
    )
    rejected("invalid_reply", lambda: validate(raw, s, reply(s, models="other-model")))
    request = prepare(raw, s)
    rejected(
        "invalid_input",
        lambda: validate(
            raw, s, request=request, p=provenance(attempt_id=__import__("uuid").UUID(int=2))
        ),
    )


def test_source_limits_and_identity_are_enforced_before_trusting_structured_request():
    from ara.docx_analysis.visible_main import VisibleLimits, VisibleViewError

    raw, _, s = fixture()
    with pytest.raises(VisibleViewError) as e:
        prepare(raw, s, limits=api().ReviewLimits(view=VisibleLimits(max_xml_nodes=3)))
    assert e.value.code == "view_limit_exceeded"
    with pytest.raises(VisibleViewError) as e:
        prepare(raw, replace(s, source_sha256="0" * 64))
    assert e.value.code == "source_mismatch"


def test_inert_fresh_process_builds_and_validates_without_model_or_database_imports():
    raw, _, _ = fixture()
    script = """
import builtins,io,os,socket,subprocess,sys,json
from pathlib import Path
from uuid import UUID
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError('Unexpected I/O or serialization')
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.visible_lists import build_list_snapshot
from ara.docx_analysis.structured_review import (
 prepare_structured_review,validate_structured_reply,ReviewProvenance)
s=build_list_snapshot(data,document_id=UUID(int=1),storage_revision=7,source_sha256=sha256(data).hexdigest())
p=ReviewProvenance(UUID(int=1),'fixture','0.1.0','synthetic-1','1'*64,'2'*64)
r=prepare_structured_review(data,s,provenance=p)
body=dict(engine='0.1.0',models='synthetic-1',issues=[],questions=[],checked=dict(fragments=len(s.fragments),active=len(s.fragments),skipped_status=0),seconds=0)
result=validate_structured_reply(data,s,provenance=p,request=r,reply=json.dumps(body).encode())
assert json.loads(result.wire_json)['document_context']['lists'][0]['label']=='1.'
assert result.no_findings is False
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


@pytest.mark.parametrize("kind", ["unknown", "prefix", "wrong_quote"])
def test_syntactically_valid_related_evidence_requires_the_exact_whole_source_fragment(kind):
    raw, _, s = fixture()
    related = dict(
        fragment_id="vf-" + "0" * 64 if kind == "unknown" else s.fragments[1].fragment_id,
        quote="Other" if kind == "prefix" else "Wrong 😀" if kind == "wrong_quote" else "Other 😀",
        status="active",
    )
    rejected(
        "invalid_reply",
        lambda: validate(raw, s, reply(s, issues=[issue(s, type="duplicate", related=related)])),
    )


def test_source_shape_is_checked_before_accessing_structured_context():
    from ara.docx_analysis.visible_main import VisibleViewError

    raw, _, s = fixture()
    for value in (None, object(), replace(s, profile="unknown/v1")):
        with pytest.raises(VisibleViewError) as e:
            prepare(raw, value)
        assert e.value.code == "invalid_snapshot"


def test_schema_reuses_unchanged_common_definitions_and_every_local_ref_resolves():
    old = json.loads(Path("contracts/docx-review-v1.json").read_text())
    schema = json.loads(Path("contracts/docx-review-v2.json").read_text())
    for name, value in old["$defs"].items():
        if name not in ("request", "result", "engine_request"):
            assert schema["$defs"][name] == value

    def walk(value):
        if type(value) is dict:
            if "$ref" in value:
                assert value["$ref"].removeprefix("#/$defs/") in schema["$defs"]
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                walk(child)
        elif type(value) is list:
            for child in value:
                walk(child)

    walk(schema)
