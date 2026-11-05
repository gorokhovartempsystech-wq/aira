"""Independent frozen review wire acceptance over synthetic saved DOCX bytes."""

import json
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from uuid import UUID

import pytest
from test_docx_visible_main import GAP, build, canonical, source


def api():
    return import_module("ara.docx_analysis.review")


def provenance(**kwargs):
    return api().ReviewProvenance(
        **(
            dict(
                attempt_id=UUID(int=1),
                execution_kind="fixture",
                engine_version="0.1.0",
                models_version="synthetic-1",
                model_sha256="1" * 64,
                adapter_sha256="2" * 64,
            )
            | kwargs
        )
    )


def fixture():
    raw, _ = source(GAP + "<w:p><w:r><w:t>Other 😀</w:t></w:r></w:p>")
    return raw, build(raw)


def prepared(raw, snapshot, **kwargs):
    return api().prepare_review(raw, snapshot, provenance=provenance(), **kwargs)


def issue(s, **kwargs):
    return (
        dict(
            id="iss-0123456789",
            type="formulation",
            severity="warning",
            light="yellow",
            confidence=0.8,
            fragment_id=s.fragments[0].fragment_id,
            span=dict(start=1, end=3, quote="bc"),
            related=None,
            explanation="Synthetic explanation",
            rule="Synthetic rule",
            suggestion=dict(before="bc", after="changed"),
            question="Why?",
        )
        | kwargs
    )


def reply(s, issues=None, **kwargs):
    issues = [issue(s)] if issues is None else issues
    return (
        dict(
            engine="0.1.0",
            models="synthetic-1",
            issues=issues,
            questions=sorted({i["question"] for i in issues if i.get("question")}),
            checked=dict(fragments=2, active=2, skipped_status=0),
            seconds=0.25,
        )
        | kwargs
    )


def validate(raw, s, body=None, *, p=None, req=None, limits=None):
    p = provenance() if p is None else p
    req = api().prepare_review(raw, s, provenance=p) if req is None else req
    return api().validate_engine_reply(
        raw,
        s,
        provenance=p,
        request=req,
        reply=canonical(reply(s) if body is None else body),
        limits=limits,
    )


def refused(code, action):
    with pytest.raises(api().ReviewError) as caught:
        action()
    assert caught.value.code == code
    assert "Synthetic explanation" not in str(caught.value)


def test_request_wire_and_literal_engine_payload_bind_exact_source():
    raw, s = fixture()
    r = prepared(raw, s)
    wire = json.loads(r.wire_json)
    engine = json.loads(r.engine_request_json)
    assert wire["schema_version"] == "docx-review/1" and wire["kind"] == "review_request"
    assert wire["source"] == dict(
        document_id=str(s.document_id), storage_revision="7", source_sha256=s.source_sha256
    )
    assert wire["snapshot_sha256"] == s.snapshot_sha256
    assert (
        wire["engine_request"]
        == engine
        == dict(
            fragments=[
                dict(
                    id=s.fragments[0].fragment_id,
                    text="abcd",
                    document="Документ",
                    status="active",
                    type="фрагмент",
                    offset=0,
                ),
                dict(
                    id=s.fragments[1].fragment_id,
                    text="Other 😀",
                    document="Документ",
                    status="active",
                    type="фрагмент",
                    offset=6,
                ),
            ],
            disabled_types=[],
            dismissed=[],
        )
    )
    assert r.wire_json == canonical(wire) and r.request_sha256 == sha256(r.wire_json).hexdigest()
    assert "abcd" not in repr(r)


def test_result_maps_gap_and_has_independently_computed_full_ids():
    raw, s = fixture()
    result = validate(raw, s)
    wire = json.loads(result.wire_json)
    f = wire["findings"][0]
    assert f["primary"]["quote"] == "bc" and f["assessment"] == "yellow"
    assert [(p["anchor"]["path"], p["start"], p["end"]) for p in f["primary"]["slices"]] == [
        ([0, 0, 0, 0], 1, 2),
        ([0, 0, 2, 0], 0, 1),
    ]
    fingerprint = {k: wire[k] for k in ("source", "snapshot_sha256", "profile", "policy_version")}
    fingerprint.update(
        {
            k: wire["provenance"][k]
            for k in ("engine_version", "models_version", "model_sha256", "adapter_sha256")
        }
    )
    fingerprint.update(
        {
            k: f[k]
            for k in (
                "type",
                "severity",
                "assessment",
                "explanation",
                "primary",
                "related",
                "question",
            )
        }
    )
    fingerprint.update(domain="docx-review-finding/1", rule="Synthetic rule")
    assert f["finding_id"] == "df-" + sha256(canonical(fingerprint)).hexdigest()
    q = wire["questions"][0]
    assert q["finding_ids"] == [f["finding_id"]] and q["text"] == "Why?"
    qkey = dict(
        domain="docx-review-question/1",
        source=wire["source"],
        snapshot_sha256=s.snapshot_sha256,
        text="Why?",
        finding_ids=[f["finding_id"]],
    )
    assert q["question_id"] == "dq-" + sha256(canonical(qkey)).hexdigest()
    assert result.findings_count == result.questions_count == 1 and not result.no_findings
    assert wire["counts"] == dict(fragments=2, findings=1, questions=1)
    assert result.result_sha256 == sha256(result.wire_json).hexdigest()
    assert "Synthetic explanation" not in repr(result)
    assert "confidence" not in f and "suggestion" not in f and "rule" not in f


@pytest.mark.parametrize("kind", ["duplicate", "contradiction"])
def test_related_full_fragment_and_question_dedup_all_origins(kind):
    raw, s = fixture()
    related = dict(fragment_id=s.fragments[1].fragment_id, quote="Other 😀", status="active")
    items = [issue(s), issue(s, id="iss-abcdef0123", type=kind, related=related, suggestion=None)]
    wire = json.loads(validate(raw, s, reply(s, items)).wire_json)
    assert len(wire["questions"]) == 1
    assert wire["questions"][0]["finding_ids"] == sorted(f["finding_id"] for f in wire["findings"])
    assert wire["findings"][1]["related"]["end"] == 7
    assert len(wire["findings"][1]["related"]["slices"]) == 1


def test_semantic_identity_ignores_transport_but_tracks_meaning():
    raw, s = fixture()
    first = json.loads(validate(raw, s).wire_json)["findings"][0]["finding_id"]
    p = provenance(attempt_id=UUID(int=2))
    changed = reply(s, [issue(s, id="iss-aaaaaaaaaa", confidence=0.2, suggestion=None)])
    assert (
        json.loads(validate(raw, s, changed, p=p).wire_json)["findings"][0]["finding_id"] == first
    )
    for mutation in (
        dict(severity="critical"),
        dict(explanation="Other explanation"),
        dict(rule="Other rule"),
        dict(question="Another?"),
    ):
        wire = json.loads(validate(raw, s, reply(s, [issue(s, **mutation)])).wire_json)
        assert wire["findings"][0]["finding_id"] != first
    p2 = provenance(model_sha256="3" * 64)
    assert json.loads(validate(raw, s, p=p2).wire_json)["findings"][0]["finding_id"] != first


@pytest.mark.parametrize("execution_kind,no_findings", [("fixture", False), ("local_model", True)])
def test_empty_protocol_branch_is_not_a_real_inference(execution_kind, no_findings):
    raw, s = fixture()
    result = validate(raw, s, reply(s, []), p=provenance(execution_kind=execution_kind))
    assert (
        result.no_findings is no_findings and result.findings_count == result.questions_count == 0
    )
    assert json.loads(result.wire_json)["provenance"]["execution_kind"] == execution_kind


@pytest.mark.parametrize(
    "mutation",
    [
        dict(type="affected"),
        dict(severity="bad"),
        dict(light="green"),
        dict(confidence=True),
        dict(confidence=1.1),
        dict(id="bad"),
        dict(explanation=""),
        dict(extra="bad"),
        dict(span=dict(start=True, end=3, quote="bc")),
        dict(span=dict(start=1, end=3, quote="xx")),
        dict(fragment_id="unknown"),
        dict(suggestion=dict(before="wrong", after="x")),
        dict(type="duplicate"),
        dict(related=dict(fragment_id="unknown", quote="Other 😀", status="active")),
    ],
)
def test_any_bad_issue_rejects_whole_reply(mutation):
    raw, s = fixture()
    refused("invalid_reply", lambda: validate(raw, s, reply(s, [issue(s, **mutation)])))


@pytest.mark.parametrize(
    "mutation",
    [
        dict(engine="wrong"),
        dict(models="wrong"),
        dict(seconds=True),
        dict(seconds=-1),
        dict(checked=dict(fragments=2, active=1, skipped_status=1)),
        dict(checked=dict(fragments=True, active=2, skipped_status=0)),
        dict(questions=[]),
        dict(questions=["Why?", "Why?"]),
        dict(questions=["Orphan"]),
        dict(extra=1),
    ],
)
def test_bad_top_metadata_counts_questions_and_keys(mutation):
    raw, s = fixture()
    refused("invalid_reply", lambda: validate(raw, s, reply(s, **mutation)))


def test_duplicate_upstream_and_local_ids_and_incomplete_related():
    raw, s = fixture()
    for items in (
        [issue(s), issue(s)],
        [issue(s), issue(s, id="iss-ffffffff00")],
        [
            issue(
                s,
                type="duplicate",
                related=dict(
                    fragment_id=s.fragments[1].fragment_id, quote="Other", status="active"
                ),
            )
        ],
    ):
        refused("invalid_reply", lambda: validate(raw, s, reply(s, items)))


def test_altered_prepared_request_and_source_admission():
    raw, s = fixture()
    req = prepared(raw, s)
    refused("invalid_input", lambda: validate(raw, s, req=replace(req, request_sha256="0" * 64)))
    other, unused = source("<w:p/>")
    refused("empty_document", lambda: prepared(other, build(other)))
    blocked, unused = source(extra_parts={"unknown.bin": b"x"})
    refused("unsupported_document", lambda: prepared(blocked, build(blocked)))


def test_limits_json_duplicate_keys_nonfinite_depth_and_corrupt_inputs():
    raw, s = fixture()
    req = prepared(raw, s)
    p = provenance()

    def call(body, limits=None):
        return api().validate_engine_reply(
            raw, s, provenance=p, request=req, reply=body, limits=limits
        )

    for bad in (
        b'{"engine":"x","engine":"y"}',
        b"\xff",
        b"[]",
        b'{"seconds":NaN}',
        b'{"x":"\\ud800"}',
    ):
        refused("invalid_reply", lambda: call(bad))
    refused("review_limit_exceeded", lambda: call(b"[" * 33 + b"]" * 33))
    valid = canonical(reply(s))
    assert call(valid, api().ReviewLimits(max_reply_bytes=len(valid))).findings_count == 1
    refused(
        "review_limit_exceeded",
        lambda: call(valid, api().ReviewLimits(max_reply_bytes=len(valid) - 1)),
    )
    refused("review_limit_exceeded", lambda: call(valid, api().ReviewLimits(max_wire_bytes=1)))
    refused("invalid_input", lambda: api().ReviewLimits(max_issues=True))
    refused("invalid_input", lambda: provenance(engine_version="new"))


def test_schema_is_new_strict_versioned_contract():
    api()
    schema = json.loads((Path.cwd() / "contracts/docx-review-v1.json").read_text())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert {
        "request",
        "result",
        "source",
        "provenance",
        "evidence",
        "finding",
        "question",
        "private_provenance",
    } <= schema["$defs"].keys()
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
