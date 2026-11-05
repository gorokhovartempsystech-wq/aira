"""Outline review survives source proof, persistence, fixture processing and filters."""

import json
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from uuid import UUID

import pytest
from test_docx_analysis_storage_codec import command, reject
from test_docx_review_v1 import canonical, issue, provenance, reply
from test_docx_structured_fixture import changed, prepared
from test_docx_visible_outline import PROFILE, build, definitions, level, paragraph, source
from test_docx_visible_plain_controls import run

from ara.docx_analysis import storage_codec as codec
from ara.docx_analysis.presentation import finding_keys, present
from ara.docx_analysis.remapping import match_findings
from ara.docx_analysis_worker.structured_fixture import (
    ReviewFixtureError,
    fixture_execution,
    reply_for,
)


def api():
    return import_module("ara.docx_analysis.outline_review")


def fixture(*, intro="Distant intro", parent_start=4, child_text="%1.%2", child="abcd"):
    def p(text):
        return "<w:p>" + run(text) + "</w:p>"

    body = p(intro) + p("Left context") + paragraph("")
    atoms = run(child[:2]) + run("PRIVATE", props="<w:vanish/>") + run(child[2:])
    nested = paragraph(level=1).replace(run("Item"), atoms)
    body += nested + p("Right context") + p("Distant end")
    defs = definitions(
        level(0, start=parent_start, fmt="upperRoman"), level(1, fmt="lowerRoman", text=child_text)
    )
    return source(body, defs)


def bundle(raw=None, *, revision=7):
    raw = fixture()[0] if raw is None else raw
    snapshot = build(raw, storage_revision=revision)
    src, attempt, request = prepared(source=(raw, snapshot))
    result = codec.capture_result(src, attempt, reply=reply_for(request))
    return src, attempt, result


def test_complete_outline_protocol_and_storage_keep_context_and_literal_evidence():
    raw, parts = fixture()
    s = build(raw)
    request = api().prepare_outline_review(raw, s, provenance=provenance())
    wire = json.loads(request.wire_json)
    engine = json.loads(request.engine_request_json)
    assert wire["schema_version"] == "docx-review/3" and wire["profile"] == PROFILE
    assert wire["engine_request"] == engine and request.wire_json == canonical(wire)
    assert [x["label"] for x in engine["document_context"]["lists"]] == ["IV.", "IV.i"]
    assert "PRIVATE" not in request.wire_json.decode()
    src, attempt, result = bundle(raw)
    assert src.format_version == 1 and src.source_data == raw and src.profile == PROFILE
    assert codec.restore_source(src).snapshot == s
    assert codec.restore_result(src, attempt, result).wire_json == result.result_data
    out = json.loads(result.result_data)
    assert (
        out["schema_version"] == "docx-review/3"
        and out["document_context"] == engine["document_context"]
    )
    primary = out["findings"][0]["primary"]
    assert primary["quote"] == "abcd" and len(primary["slices"]) == 2
    assert "Учебный пример" in out["findings"][0]["explanation"] and not result.no_findings
    from xml.etree import ElementTree as ET

    values = []
    for item in primary["slices"]:
        node = ET.fromstring(parts[item["anchor"]["part_name"]])
        for index in item["anchor"]["path"]:
            node = node[index]
        values.append(node.text[item["start"] : item["end"]])
    assert "".join(values) == "abcd"


def test_generated_label_is_not_valid_literal_evidence():
    raw, _ = fixture()
    s = build(raw)
    p = provenance()
    request = api().prepare_outline_review(raw, s, provenance=p)
    f = next(f for f in s.fragments if f.text == "abcd")
    valid = reply(
        s,
        [
            issue(
                s,
                fragment_id=f.fragment_id,
                span=dict(start=0, end=4, quote="abcd"),
                suggestion=None,
            )
        ],
        checked=dict(fragments=len(s.fragments), active=len(s.fragments), skipped_status=0),
    )
    accepted = api().validate_outline_reply(
        raw, s, provenance=p, request=request, reply=canonical(valid)
    )
    assert accepted.findings_count == 1
    bad = json.loads(canonical(valid))
    bad["issues"][0]["span"]["quote"] = "IV.i"
    with pytest.raises(api().ReviewError) as error:
        api().validate_outline_reply(raw, s, provenance=p, request=request, reply=canonical(bad))
    assert error.value.code == "invalid_reply"


@pytest.mark.parametrize("target", ["manifest", "request", "result", "attempt", "profile"])
def test_rehashed_context_or_identity_never_replaces_original_source(target):
    src, a, r = bundle()
    if target == "attempt":
        a = replace(a, attempt_id=UUID(int=99))
    elif target == "profile":
        src = replace(src, profile="docx-analysis/final-visible-direct-lists-v1")
    else:
        data = (
            src.snapshot_data
            if target == "manifest"
            else a.request_data
            if target == "request"
            else r.result_data
        )
        body = json.loads(data)
        context = (
            body
            if target == "manifest"
            else body["engine_request"]["document_context"]
            if target == "request"
            else body["document_context"]
        )
        context["lists"][1]["label"] = "99."
        raw = canonical(body)
        if target == "manifest":
            src = replace(src, snapshot_data=raw, snapshot_sha256=sha256(raw).hexdigest())
        elif target == "request":
            a = replace(a, request_data=raw, request_sha256=sha256(raw).hexdigest())
        else:
            r = replace(r, result_data=raw, result_sha256=sha256(raw).hexdigest())
    reject("corrupt_record", lambda: codec.restore_result(src, a, r))


@pytest.mark.parametrize(
    "key,value",
    [
        ("level", 9),
        ("level", True),
        ("format", "upperLetter"),
        ("label", "X" * 32),
        ("label", "😀" * 16),
    ],
)
def test_fixture_new_pair_has_closed_outline_shape(key, value):
    raw = fixture()[0]
    _, _, message = prepared(source=(raw, build(raw)))
    body = json.loads(message.payload)
    body["engine_request"]["document_context"]["lists"][1][key] = value
    with pytest.raises(ReviewFixtureError):
        reply_for(changed(message, body))


@pytest.mark.parametrize(
    "version,profile",
    [
        ("docx-review/2", PROFILE),
        ("docx-review/3", "docx-analysis/final-visible-direct-lists-v1"),
        ("docx-review/4", PROFILE),
    ],
)
def test_fixture_rejects_mixed_and_unknown_pairs(version, profile):
    raw = fixture()[0]
    _, _, message = prepared(source=(raw, build(raw)))
    body = json.loads(message.payload)
    body.update(schema_version=version, profile=profile)
    with pytest.raises(ReviewFixtureError):
        reply_for(changed(message, body))


def test_existing_fixture_pair_does_not_gain_outline_levels():
    _, _, message = prepared()
    body = json.loads(message.payload)
    body["engine_request"]["document_context"]["lists"][0]["level"] = 1
    with pytest.raises(ReviewFixtureError):
        reply_for(changed(message, body))


def test_codec_counts_generated_characters_with_no_schema_change():
    raw = fixture()[0]
    s = build(raw)
    cost = sum(len(f.text) for f in s.fragments) + sum(
        len(i.label) + (i.suffix != "nothing") for i in s.lists
    )
    limits = codec.CodecLimits(max_text_characters=cost)
    src = codec.capture_source(
        raw, s, command=command(s), execution=fixture_execution(), limits=limits
    )
    assert codec.restore_source(src, limits=limits).snapshot == s
    reject(
        "codec_limit_exceeded",
        lambda: codec.restore_source(src, limits=replace(limits, max_text_characters=cost - 1)),
    )


def test_filters_and_exact_source_hide_keep_full_context_and_original_result():
    records = bundle()
    original = records[2].result_data
    key = finding_keys(*records)[0].key
    for kw in (dict(hidden_keys=[key]), dict(disabled_types=["formulation"], show_questions=False)):
        view = present(*records, **kw)
        body = json.loads(view.wire_json)
        assert body["schema_version"] == "docx-review-view/3" and body["profile"] == PROFILE
        assert body["document_context"] == json.loads(original)["document_context"]
        assert view.no_visible_findings and not view.no_findings and body["fixture"]
        assert "private_provenance" not in body and "hidden_keys" not in body
    assert records[2].result_data == original
    shown = present(*records, hidden_keys=[key], show_hidden=True)
    assert shown.visible_findings == 1


@pytest.mark.parametrize(
    "change,matches", [("distant", True), ("counter", False), ("label", False), ("text", False)]
)
def test_cross_source_hide_requires_same_outline_semantics(change, matches):
    old = bundle()
    kw = (
        {"intro": "Changed distant intro"}
        if change == "distant"
        else {"parent_start": 5}
        if change == "counter"
        else {"child_text": "%1-%2"}
        if change == "label"
        else {"child": "abXY"}
    )
    new = bundle(fixture(**kw)[0], revision=8)
    transfers = match_findings(old, new)
    assert bool(transfers) == matches
    if matches:
        assert len(transfers) == 1
        assert present(*new, hidden_keys=[transfers[0].current_key]).no_visible_findings


def test_schema_three_is_self_contained_and_previous_versions_stay_distinct():
    schema = json.loads(Path("contracts/docx-review-v3.json").read_text())
    view = json.loads(Path("contracts/docx-review-view-v3.json").read_text())
    old = json.loads(Path("contracts/docx-review-v2.json").read_text())
    assert (
        schema["$id"] == "urn:aira:docx-review:3" and view["$id"] == "urn:aira:docx-review-view:3"
    )
    for name in ("request", "result"):
        assert schema["$defs"][name]["properties"]["schema_version"]["const"] == "docx-review/3"
        assert schema["$defs"][name]["properties"]["profile"]["const"] == PROFILE
        assert old["$defs"][name]["properties"]["schema_version"]["const"] == "docx-review/2"
    props = schema["$defs"]["list_item"]["properties"]
    assert props["level"] == {"type": "integer", "minimum": 0, "maximum": 8}
    assert props["format"]["enum"] == ["decimal", "bullet", "upperRoman", "lowerRoman"]
    assert (
        props["label"]["maxLength"] == 31
        and old["$defs"]["list_item"]["properties"]["level"]["const"] == 0
    )
    body = json.loads(present(*bundle()).wire_json)
    assert (
        set(view["required"]) == set(view["properties"]) == set(body)
        and view["additionalProperties"] is False
    )
    assert view["properties"]["schema_version"]["const"] == "docx-review-view/3"
    for name in (
        "source",
        "provenance",
        "anchor",
        "slice",
        "evidence",
        "finding",
        "coverage",
        "fragment_id",
        "list_item",
        "note_reference",
        "document_context",
    ):
        assert view["$defs"][name] == schema["$defs"][name]
    for document in (schema, view):

        def refs(value):
            if type(value) is dict:
                if "$ref" in value:
                    assert (
                        value["$ref"].startswith("#/$defs/")
                        and value["$ref"][8:] in document["$defs"]
                    )
                for child in value.values():
                    refs(child)
            elif type(value) is list:
                for child in value:
                    refs(child)

        refs(document)


@pytest.mark.parametrize("hidden", [False, True])
def test_outline_resolution_work_limit_includes_labels_on_each_source_pass(hidden):
    from test_docx_structured_remapping import resolution_input

    from ara.documents.storage import DocumentError
    from ara.docx_review_resolution._resolve import resolve

    raw = fixture()[0]
    old, new = bundle(raw), bundle(raw, revision=8)
    s = json.loads(new[0].snapshot_data)
    cost = len(s["analysis_text"]) + sum(
        len(i["label"]) + (i["suffix"] != "nothing") for i in s["lists"]
    )
    passes = 3 if hidden else 1
    inputs = resolution_input(old, new, limit=passes * cost, hidden=hidden)
    out = resolve(inputs)
    assert bool(out.hidden_keys) is hidden and out.decisions == inputs.decisions
    with pytest.raises(DocumentError) as error:
        resolve(resolution_input(old, new, limit=passes * cost - 1, hidden=hidden))
    assert error.value.code == "preferences_resolution_limit" and error.value.status == 413


@pytest.mark.parametrize("host", ["macos", "windows"])
def test_existing_child_bodies_transport_outline_reply_without_new_native_protocol(
    monkeypatch, host
):
    from types import SimpleNamespace

    from ara.docx_analysis_worker.wire import StreamDecoder

    raw = fixture()[0]
    src, attempt, message = prepared(source=(raw, build(raw)))
    child = import_module("ara.docx_analysis_worker." + host + "._fixture_child")
    frames = []
    if host == "macos":

        def write(fd, data):
            assert fd == 1
            frames.append(bytes(data))
            return len(data)

        monkeypatch.setattr(child.os, "write", write)
        code = child.run_fixture(message.binding, message, "review2")
    else:
        code = child.run_fixture(
            SimpleNamespace(), message.binding, message, "review2", frames.append, 0
        )
    decoder = StreamDecoder(
        message.binding, lane="events", expected_execution_spec_sha256=src.execution_spec_sha256
    )
    messages = decoder.feed(b"".join(frames))
    decoder.finish()
    assert code == 0 and [m.kind for m in messages] == ["ready", "stage", "stage", "result"]
    result = codec.capture_result(src, attempt, reply=messages[-1].payload)
    assert json.loads(result.result_data)["schema_version"] == "docx-review/3"


def test_same_file_and_model_do_not_transfer_hides_across_source_profiles():
    from test_docx_structured_presentation import bundle as old_bundle

    old = old_bundle(spec=fixture_execution())
    raw = old[0].source_data
    s = build(raw, document_id=old[0].document_id)
    src = codec.capture_source(raw, s, command=command(s), execution=fixture_execution())
    a = codec.prepare_attempt(src, attempt_id=UUID(int=2))
    reply_body = json.loads(old[2].reply_data)
    reply_body["issues"][0]["fragment_id"] = s.fragments[0].fragment_id
    r = codec.capture_result(src, a, reply=canonical(reply_body))
    assert (
        json.loads(r.result_data)["findings"][0]["primary"]["quote"]
        == json.loads(old[2].result_data)["findings"][0]["primary"]["quote"]
    )
    assert src.source_sha256 == old[0].source_sha256
    assert match_findings(old, (src, a, r)) == ()
