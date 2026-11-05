"""Structured review preserves generated context without changing literal evidence."""

import json
from dataclasses import asdict, replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree as ET

import pytest
from test_docx_review_v1 import canonical, issue, provenance, reply
from test_docx_visible_lists import build, paragraph
from test_docx_visible_main import rehash
from test_docx_visible_plain_controls import run
from test_docx_visible_unlisted import NUMPR, source


def api():
    return import_module("ara.docx_analysis.structured_review")


def fixture():
    body = (
        "<w:p><w:pPr>"
        + NUMPR
        + "</w:pPr>"
        + run("ab")
        + run("PRIVATE", props="<w:vanish/>")
        + run("cd")
        + "</w:p><w:p>"
        + run("Other 😀")
        + "</w:p>"
    )
    raw, parts = source(body)
    return raw, parts, build(raw)


def context(s):
    return json.loads(
        canonical(
            dict(
                lists=[asdict(x) for x in s.lists],
                note_references=[asdict(x) for x in s.references],
            )
        )
    )


def prepare(raw, s, **kw):
    return api().prepare_structured_review(
        raw, s, provenance=kw.pop("provenance", provenance()), **kw
    )


def validate(raw, s, body=None, *, request=None, p=None, limits=None):
    p = provenance() if p is None else p
    request = prepare(raw, s, provenance=p) if request is None else request
    return api().validate_structured_reply(
        raw,
        s,
        provenance=p,
        request=request,
        reply=canonical(reply(s) if body is None else body),
        limits=limits,
    )


def rejected(code, call):
    with pytest.raises(api().ReviewError) as e:
        call()
    assert e.value.code == code


def test_canonical_request_preserves_context_in_both_engine_and_outer_payloads():
    raw, _, s = fixture()
    r = prepare(raw, s)
    outer, engine = json.loads(r.wire_json), json.loads(r.engine_request_json)
    assert outer["schema_version"] == "docx-review/2" and outer["profile"] == s.profile
    assert outer["engine_request"] == engine
    assert engine["document_context"] == context(s)
    assert engine["fragments"] == [
        dict(
            id=f.fragment_id,
            text=f.text,
            document="Документ",
            status="active",
            type="фрагмент",
            offset=f.analysis_start,
        )
        for f in s.fragments
    ]
    assert engine["disabled_types"] == engine["dismissed"] == []
    assert engine["document_context"]["lists"][0]["label"] == "1."
    assert outer["snapshot_sha256"] == s.snapshot_sha256
    assert r.wire_json == canonical(outer) and r.engine_request_json == canonical(engine)
    assert r.request_sha256 == sha256(r.wire_json).hexdigest()
    assert "PRIVATE" not in r.wire_json.decode() + repr(r)


def test_result_retains_exact_context_and_maps_only_real_literal_characters():
    raw, parts, s = fixture()
    result = validate(raw, s)
    out = json.loads(result.wire_json)
    assert out["schema_version"] == "docx-review/2" and out["profile"] == s.profile
    assert out["document_context"] == context(s)
    f = out["findings"][0]
    assert f["primary"]["quote"] == "bc" and len(f["primary"]["slices"]) == 2
    text = []
    for item in f["primary"]["slices"]:
        node = ET.fromstring(parts[item["anchor"]["part_name"]])
        for index in item["anchor"]["path"]:
            node = node[index]
        text.append(node.text[item["start"] : item["end"]])
    assert "".join(text) == "bc"
    assert result.no_findings is False and out["no_findings"] is False
    assert result.findings_count == result.questions_count == 1
    assert result.result_sha256 == sha256(result.wire_json).hexdigest()


def test_attempt_identity_does_not_change_semantic_finding_identity():
    raw, _, s = fixture()
    first = json.loads(validate(raw, s).wire_json)
    second = json.loads(validate(raw, s, p=provenance(attempt_id=UUID(int=99))).wire_json)
    assert first["findings"][0]["finding_id"] == second["findings"][0]["finding_id"]
    assert first["questions"][0]["question_id"] == second["questions"][0]["question_id"]
    assert first["request_sha256"] != second["request_sha256"]


def test_label_change_changes_source_semantic_binding_without_altering_literal_quotes():
    from test_docx_visible_unlisted import DEFS

    raw, _, s = fixture()
    first = json.loads(validate(raw, s).wire_json)
    body = (
        "<w:p><w:pPr>"
        + NUMPR
        + "</w:pPr>"
        + run("ab")
        + run("PRIVATE", props="<w:vanish/>")
        + run("cd")
        + "</w:p><w:p>"
        + run("Other 😀")
        + "</w:p>"
    )
    changed, _ = source(body, DEFS.replace('w:val="%1."', 'w:val="Requirement %1:"'))
    t = build(changed)
    second = json.loads(validate(changed, t).wire_json)
    assert (
        first["findings"][0]["primary"]["quote"]
        == second["findings"][0]["primary"]["quote"]
        == "bc"
    )
    assert first["findings"][0]["finding_id"] != second["findings"][0]["finding_id"]
    assert first["document_context"] != second["document_context"]


@pytest.mark.parametrize("part", ["label", "anchor", "list_removal"])
def test_rehashed_snapshot_context_is_not_source_authority(part):
    from ara.docx_analysis.visible_main import VisibleViewError

    raw, _, s = fixture()
    item = s.lists[0]
    lists = (
        ()
        if part == "list_removal"
        else (
            replace(item, label="999.")
            if part == "label"
            else replace(item, properties_anchor=item.definition_anchor),
        )
    )
    fake = rehash(replace(s, lists=lists))
    with pytest.raises(VisibleViewError) as e:
        prepare(raw, fake)
    assert e.value.code == "invalid_snapshot"


@pytest.mark.parametrize("target", ["wire", "engine", "both", "hash"])
def test_forged_prepared_context_or_hash_is_rejected_before_result_publication(target):
    raw, _, s = fixture()
    original = prepare(raw, s)
    outer, engine = json.loads(original.wire_json), json.loads(original.engine_request_json)
    outer["engine_request"]["document_context"]["lists"][0]["label"] = "999."
    engine["document_context"]["lists"][0]["label"] = "999."
    fake = replace(
        original,
        wire_json=canonical(outer) if target in ("wire", "both") else original.wire_json,
        engine_request_json=canonical(engine)
        if target in ("engine", "both")
        else original.engine_request_json,
        request_sha256="0" * 64
        if target == "hash"
        else sha256(canonical(outer)).hexdigest()
        if target in ("wire", "both")
        else original.request_sha256,
    )
    rejected("invalid_input", lambda: validate(raw, s, request=fake))


@pytest.mark.parametrize(
    "change",
    [
        dict(span=dict(start=0, end=2, quote="1.")),
        dict(fragment_id="vf-" + "0" * 64),
        dict(span=dict(start=1, end=3, quote="wrong")),
        dict(related=dict(fragment_id="vf-" + "0" * 64, quote="Other 😀")),
    ],
)
def test_generated_label_or_wrong_source_spans_never_receive_fabricated_slices(change):
    raw, _, s = fixture()
    rejected("invalid_reply", lambda: validate(raw, s, reply(s, issues=[issue(s, **change)])))


def test_old_and_structured_profile_admission_remain_mutually_closed():
    from test_docx_review_v1 import fixture as old_fixture

    from ara.docx_analysis.review import prepare_review
    from ara.docx_analysis.visible_main import VisibleViewError

    raw, _, s = fixture()
    with pytest.raises(VisibleViewError) as e:
        prepare_review(raw, s, provenance=provenance())
    assert e.value.code == "invalid_snapshot"
    old_raw, old = old_fixture()
    with pytest.raises(VisibleViewError) as e:
        prepare(old_raw, old)
    assert e.value.code == "invalid_snapshot"


def test_no_literal_text_and_incomplete_documents_are_not_implicit_review_success():
    raw, _ = source(paragraph(""))
    s = build(raw)
    assert s.complete and s.lists and s.fragments == ()
    rejected("empty_document", lambda: prepare(raw, s))
    raw, _ = source(paragraph("Private", level=1))
    s = build(raw)
    assert not s.complete
    rejected("unsupported_document", lambda: prepare(raw, s))


def test_empty_findings_still_preserve_context_and_fixture_is_not_real_analysis():
    raw, _, s = fixture()
    result = validate(raw, s, reply(s, issues=[]))
    wire = json.loads(result.wire_json)
    assert wire["document_context"] == context(s) and wire["findings"] == wire["questions"] == []
    assert wire["no_findings"] is False and result.no_findings is False


def test_schema_v2_is_self_contained_closed_and_v1_remains_distinct():
    api()
    schema = json.loads(Path("contracts/docx-review-v2.json").read_text())
    old = json.loads(Path("contracts/docx-review-v1.json").read_text())
    assert schema["$id"] == "urn:aira:docx-review:2" and old["$id"] == "urn:aira:docx-review:1"
    for name in ("request", "result"):
        assert schema["$defs"][name]["properties"]["schema_version"]["const"] == "docx-review/2"
        assert old["$defs"][name]["properties"]["schema_version"]["const"] == "docx-review/1"
    for name in ("engine_request", "result"):
        assert "document_context" in schema["$defs"][name]["required"]
        assert "document_context" not in old["$defs"][name]["properties"]
    for name in ("list_item", "note_reference", "document_context"):
        d = schema["$defs"][name]
        assert d["additionalProperties"] is False and set(d["required"]) == set(d["properties"])
    assert schema["$defs"]["list_item"]["properties"]["label"]["maxLength"] == 4096
    assert schema["$defs"]["list_item"]["properties"]["level"]["const"] == 0
    assert schema["$defs"]["document_context"]["properties"]["lists"]["maxItems"] == 10000

    def refs(value):
        if type(value) is dict:
            if "$ref" in value:
                assert value["$ref"].startswith("#/$defs/")
            for child in value.values():
                refs(child)
        elif type(value) is list:
            for child in value:
                refs(child)

    refs(schema)
