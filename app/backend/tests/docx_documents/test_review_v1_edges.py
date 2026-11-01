"""Review batch work bounds, strict hostile JSON, and no application side effects."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from docx_projection_fixtures import package
from test_docx_review_v1 import fixture, issue, prepared, provenance, refused, reply, validate
from test_docx_visible_main import GAP, build, canonical

from ara.docx_analysis import review as api
from ara.docx_analysis.visible_main import VisibleLimits, VisibleViewError


def test_metadata_suggestion_question_and_final_wire_caps():
    raw, s = fixture()
    refused(
        "review_limit_exceeded",
        lambda: validate(raw, s, limits=api.ReviewLimits(max_metadata_characters=8)),
    )
    refused(
        "review_limit_exceeded",
        lambda: validate(raw, s, limits=api.ReviewLimits(max_suggestion_characters=5)),
    )
    items = [issue(s), issue(s, id="iss-abcdef0123", question="What?")]
    refused(
        "review_limit_exceeded",
        lambda: validate(raw, s, reply(s, items), limits=api.ReviewLimits(max_questions=1)),
    )
    refused(
        "review_limit_exceeded",
        lambda: validate(raw, s, reply(s, items), limits=api.ReviewLimits(max_issues=1)),
    )
    result = validate(raw, s)
    size = len(result.wire_json)
    assert size > len(prepared(raw, s).wire_json)
    assert validate(raw, s, limits=api.ReviewLimits(max_wire_bytes=size)) == result
    refused(
        "review_limit_exceeded",
        lambda: validate(raw, s, limits=api.ReviewLimits(max_wire_bytes=size - 1)),
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_nonfinite_reply_confidence_never_becomes_valid(value):
    raw, s = fixture()
    payload = json.dumps(reply(s, [issue(s, confidence=value)])).encode()
    p = provenance()
    req = prepared(raw, s)
    refused(
        "invalid_reply",
        lambda: api.validate_engine_reply(raw, s, provenance=p, request=req, reply=payload),
    )


def test_related_self_wrong_status_and_bad_unicode():
    raw, s = fixture()
    variants = [
        issue(
            s,
            type="duplicate",
            related=dict(fragment_id=s.fragments[0].fragment_id, quote="abcd", status="active"),
        ),
        issue(
            s,
            type="contradiction",
            related=dict(
                fragment_id=s.fragments[1].fragment_id, quote="Other 😀", status="deprecated"
            ),
        ),
    ]
    for item in variants:
        refused("invalid_reply", lambda: validate(raw, s, reply(s, [item])))
    payload = json.dumps(reply(s, [issue(s, explanation="\ud800")])).encode()
    refused(
        "invalid_reply",
        lambda: api.validate_engine_reply(
            raw, s, provenance=provenance(), request=prepared(raw, s), reply=payload
        ),
    )


def test_exact_provenance_limits_request_and_no_foreign_hooks():
    class Trap:
        def __eq__(self, other):
            raise AssertionError("eq called")

        def __repr__(self):
            raise AssertionError("repr called")

    raw, s = fixture()
    req = prepared(raw, s)
    refused("invalid_input", lambda: validate(raw, s, req=replace(req, wire_json=Trap())))
    refused("invalid_input", lambda: provenance(attempt_id=object.__new__(UUID)))
    limits = api.ReviewLimits()
    object.__setattr__(limits.view, "max_runs", False)
    refused("invalid_input", lambda: validate(raw, s, limits=limits))
    p = provenance()
    object.__setattr__(p, "execution_kind", Trap())
    refused("invalid_input", lambda: validate(raw, s, p=p, req=req))


def test_single_batch_source_rebuild_including_empty_result(monkeypatch):
    from ara.docx_analysis.visible_main import _build

    raw, s = fixture()
    req = prepared(raw, s)
    original = _build.read_style_context
    calls = []

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(_build, "read_style_context", spy)
    items = [issue(s, id=f"iss-{i:010x}", explanation=f"Synthetic issue {i}") for i in range(100)]
    assert validate(raw, s, reply(s, items), req=req).findings_count == 100
    assert calls == [1]
    calls.clear()
    assert validate(raw, s, reply(s, []), req=req).findings_count == 0
    assert calls == [1]


def test_brackets_quotes_and_empty_question_are_not_json_structure():
    raw, s = fixture()
    explanation = 'Literal brackets [[[[[[[ and escaped "quoted" \\slashes'
    result = validate(raw, s, reply(s, [issue(s, explanation=explanation, question="")]))
    wire = json.loads(result.wire_json)
    assert wire["findings"][0]["explanation"] == explanation
    assert wire["findings"][0]["question"] is None and wire["questions"] == []


def test_source_mismatch_and_nested_mapping_budget_are_not_relabelled():
    raw, s = fixture()
    req = prepared(raw, s)
    with pytest.raises(VisibleViewError) as caught:
        api.validate_engine_reply(
            raw + b"x", s, provenance=provenance(), request=req, reply=canonical(reply(s))
        )
    assert caught.value.code == "source_mismatch"
    with pytest.raises(VisibleViewError) as caught:
        validate(raw, s, req=req, limits=api.ReviewLimits(view=VisibleLimits(max_mapped_slices=1)))
    assert caught.value.code == "view_limit_exceeded"


def test_schema_references_are_local_complete_and_object_keys_are_required():
    schema = json.loads((Path.cwd() / "contracts/docx-review-v1.json").read_text())
    pending = [schema]
    while pending:
        node = pending.pop()
        if type(node) is dict:
            if "$ref" in node:
                assert node["$ref"].startswith("#/$defs/")
                assert node["$ref"].removeprefix("#/$defs/") in schema["$defs"]
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["properties"]) == set(node["required"])
            pending.extend(node.values())
        elif type(node) is list:
            pending.extend(node)


def test_fresh_process_review_has_no_application_io():
    raw, s = fixture()
    script = """
import builtins,io,os,socket,subprocess,sys,json
from pathlib import Path
from hashlib import sha256
from uuid import UUID
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.visible_main import build_visible_snapshot
from ara.docx_analysis.review import prepare_review,validate_engine_reply,ReviewProvenance
s=build_visible_snapshot(data,document_id=UUID(int=1),storage_revision=1,source_sha256=sha256(data).hexdigest())
p=ReviewProvenance(UUID(int=2),"fixture","0.1.0","synthetic","1"*64,"2"*64)
r=prepare_review(data,s,provenance=p)
body=dict(engine="0.1.0",models="synthetic",issues=[],questions=[],checked=dict(fragments=2,active=2,skipped_status=0),seconds=0)
v=validate_engine_reply(data,s,provenance=p,request=r,reply=json.dumps(body).encode())
assert not v.no_findings and v.findings_count==0
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


def test_oversize_repeated_evidence_fails_before_hashing_whole_batch(monkeypatch):
    from ara.docx_analysis.review import _validate

    raw = package(
        GAP + "<w:p><w:r><w:t>Other 😀</w:t></w:r></w:p>", main_part="long/" + "a" * 2000 + ".xml"
    )[0]
    s = build(raw)
    items = [issue(s, id=f"iss-{i:010x}", explanation=f"Issue {i}") for i in range(100)]
    calls = []
    original = _validate.fingerprint

    def spy(*a, **kw):
        calls.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(_validate, "fingerprint", spy)
    refused(
        "review_limit_exceeded",
        lambda: validate(raw, s, reply(s, items), limits=api.ReviewLimits(max_wire_bytes=120000)),
    )
    assert len(calls) < 20
