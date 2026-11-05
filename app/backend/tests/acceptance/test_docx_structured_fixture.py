"""Fixture2 explicitly consumes source-derived structure and remains synthetic."""

import base64
import json
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from uuid import UUID

import pytest
from test_docx_analysis_storage_codec import command
from test_docx_review_v1 import canonical
from test_docx_review_v1 import fixture as legacy_fixture
from test_docx_review_v2 import fixture

from ara.docx_analysis.storage_codec import capture_result, capture_source, prepare_attempt
from ara.docx_analysis_worker.wire import StreamDecoder, WireBinding, encode_message


def api():
    return import_module("ara.docx_analysis_worker.structured_fixture")


def prepared(*, legacy=False, source=None, spec=None):
    if source is None:
        if legacy:
            raw, s = legacy_fixture()
        else:
            raw, _, s = fixture()
    else:
        raw, s = source
    src = capture_source(
        raw, s, command=command(s), execution=api().fixture_execution() if spec is None else spec
    )
    attempt = prepare_attempt(src, attempt_id=UUID(int=1))
    binding = WireBinding(UUID(int=10), attempt.attempt_id)
    frame = encode_message(
        binding,
        kind="run",
        seq=0,
        values=dict(
            worker_instance_id=str(UUID(int=11)),
            claim_fence=1,
            request_sha256=attempt.request_sha256,
            execution_spec_sha256=src.execution_spec_sha256,
            request_b64=base64.b64encode(attempt.request_data).decode(),
            execution_spec_b64=base64.b64encode(src.execution_spec).decode(),
        ),
    )
    decoder = StreamDecoder(binding, lane="request")
    (message,) = decoder.feed(frame)
    decoder.finish()
    return src, attempt, message


def changed(message, body):
    raw = canonical(body)
    return replace(
        message, payload=raw, values=dict(message.values, request_sha256=sha256(raw).hexdigest())
    )


def rejected(call):
    with pytest.raises(api().ReviewFixtureError) as e:
        call()
    assert "PRIVATE" not in str(e.value) and "Other 😀" not in str(e.value)


@pytest.mark.parametrize("legacy", [False, True])
def test_fixed_execution_and_supported_wire_pairs_return_source_valid_synthetic_results(legacy):
    from ara.docx_analysis_worker.review_fixture import fixture_execution as old_execution

    spec = api().fixture_execution()
    assert spec.execution_kind == "fixture" and spec.engine_version == "0.1.0"
    assert spec.models_version == "aira-review-fixture-2"
    assert spec.model_sha256 == sha256(b"aira-review-fixture-model/2").hexdigest()
    assert spec.adapter_sha256 == sha256(b"aira-review-fixture-adapter/2").hexdigest()
    assert spec != old_execution()
    src, attempt, request = prepared(legacy=legacy)
    wire = json.loads(request.payload)
    assert wire["schema_version"] == ("docx-review/1" if legacy else "docx-review/2")
    raw_reply = api().reply_for(request)
    assert raw_reply == api().reply_for(request)
    result = capture_result(src, attempt, reply=raw_reply)
    out = json.loads(result.result_data)
    assert result.findings_count == result.questions_count == 1 and not result.no_findings
    finding = out["findings"][0]
    assert "Учебный пример" in finding["explanation"]
    assert "Реальная модель не запускалась" in finding["explanation"]
    assert "Учебный пример" in finding["question"]
    assert finding["primary"]["quote"] == "abcd"
    assert finding["primary"]["start"] == 0 and finding["primary"]["end"] == 4
    assert out["provenance"]["models_version"] == "aira-review-fixture-2"
    assert out.get("document_context") == wire["engine_request"].get("document_context")
    assert "PRIVATE" not in raw_reply.decode()


def test_actual_aira_heading_and_list_select_literal_list_fragment_and_show_label_as_context():
    from test_docx_visible_lists import build

    from ara.docx_package.creation import NewParagraph, create_docx

    raw = create_docx(
        (
            NewParagraph("Title", "heading1"),
            NewParagraph("First item", "numbered"),
            NewParagraph("Second item", "numbered"),
        )
    )
    s = build(raw)
    src, a, request = prepared(source=(raw, s))
    out = json.loads(capture_result(src, a, reply=api().reply_for(request)).result_data)
    finding = out["findings"][0]
    assert finding["primary"]["fragment_id"] == s.lists[0].fragment_ids[0]
    assert finding["primary"]["quote"] == "First item" and finding["primary"]["start"] == 0
    assert s.lists[0].label in finding["explanation"]
    assert out["document_context"]["lists"][0]["label"] == "1."


def test_old_and_new_executors_do_not_share_execution_identity():
    from ara.docx_analysis_worker.review_fixture import (
        ReviewFixtureError,
        fixture_execution,
        reply_for,
    )

    _, _, old = prepared(legacy=True, spec=fixture_execution())
    rejected(lambda: api().reply_for(old))
    for legacy in (False, True):
        _, _, new = prepared(legacy=legacy)
        with pytest.raises(ReviewFixtureError):
            reply_for(new)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_context",
        "extra_context",
        "missing_lists",
        "notes_not_array",
        "lists_not_array",
        "num_bool",
        "level",
        "ordinal_bool",
        "ordinal_negative",
        "format",
        "suffix",
        "label_type",
        "label_size",
        "list_extra",
        "list_missing",
        "duplicate_item",
        "unknown_fragment",
        "duplicate_fragment",
        "anchor_hash",
        "anchor_path_bool",
        "anchor_depth",
        "anchor_part",
        "anchor_extra",
        "properties_part",
        "override_part",
        "legacy_version",
        "unknown_profile",
        "wrong_policy",
        "local_model",
        "source_id",
        "source_revision",
        "attempt",
        "request_hash",
        "spec_hash",
        "seq_bool",
        "filters",
        "fragment_extra",
        "fragment_empty",
        "fragment_duplicate",
        "offset_bool",
        "duplicate_json",
    ],
)
def test_invalid_structure_or_binding_is_rejected_atomically_without_payload_diagnostics(fault):
    _, _, request = prepared()
    body = json.loads(request.payload)
    engine = body["engine_request"]
    context = engine["document_context"]
    item = context["lists"][0]
    if fault == "request_hash":
        request = replace(request, values=dict(request.values, request_sha256="0" * 64))
    elif fault == "spec_hash":
        request = replace(request, values=dict(request.values, execution_spec_sha256="0" * 64))
    elif fault == "attempt":
        request = replace(request, binding=WireBinding(request.binding.run_id, UUID(int=99)))
    elif fault == "seq_bool":
        request = replace(request, seq=False)
    elif fault == "duplicate_json":
        raw = b'{"PRIVATE":0,"PRIVATE":1}'
        request = replace(
            request,
            payload=raw,
            values=dict(request.values, request_sha256=sha256(raw).hexdigest()),
        )
    else:
        if fault == "missing_context":
            del engine["document_context"]
        elif fault == "extra_context":
            context["PRIVATE"] = 0
        elif fault == "missing_lists":
            del context["lists"]
        elif fault == "notes_not_array":
            context["note_references"] = {}
        elif fault == "lists_not_array":
            context["lists"] = {}
        elif fault == "num_bool":
            item["num_id"] = True
        elif fault == "level":
            item["level"] = 1
        elif fault == "ordinal_bool":
            item["ordinal"] = False
        elif fault == "ordinal_negative":
            item["ordinal"] = -1
        elif fault == "format":
            item["format"] = "none"
        elif fault == "suffix":
            item["suffix"] = "line"
        elif fault == "label_type":
            item["label"] = None
        elif fault == "label_size":
            item["label"] = "a" * 4097
        elif fault == "list_extra":
            item["PRIVATE"] = True
        elif fault == "list_missing":
            del item["instance_anchor"]
        elif fault == "duplicate_item":
            context["lists"].append(json.loads(canonical(item)))
        elif fault == "unknown_fragment":
            item["fragment_ids"] = ["vf-" + "0" * 64]
        elif fault == "duplicate_fragment":
            item["fragment_ids"] *= 2
        elif fault == "anchor_hash":
            item["paragraph_anchor"]["source_sha256"] = "0" * 64
        elif fault == "anchor_path_bool":
            item["paragraph_anchor"]["path"] = [True]
        elif fault == "anchor_depth":
            item["paragraph_anchor"]["path"] = [0] * 129
        elif fault == "anchor_part":
            item["paragraph_anchor"]["part_name"] = "../PRIVATE"
        elif fault == "anchor_extra":
            item["paragraph_anchor"]["PRIVATE"] = True
        elif fault == "properties_part":
            item["properties_anchor"]["part_name"] = "different.xml"
        elif fault == "override_part":
            item["start_override_anchor"] = json.loads(canonical(item["paragraph_anchor"]))
        elif fault == "legacy_version":
            body["schema_version"] = "docx-review/1"
        elif fault == "unknown_profile":
            body["profile"] = "unknown/v1"
        elif fault == "wrong_policy":
            body["policy_version"] = "unknown/v1"
        elif fault == "local_model":
            body["provenance"]["execution_kind"] = "local_model"
        elif fault == "source_id":
            body["source"]["document_id"] = "PRIVATE"
        elif fault == "source_revision":
            body["source"]["storage_revision"] = "01"
        elif fault == "filters":
            engine["disabled_types"] = ["formulation"]
        elif fault == "fragment_extra":
            engine["fragments"][0]["PRIVATE"] = True
        elif fault == "fragment_empty":
            engine["fragments"][0]["text"] = ""
        elif fault == "fragment_duplicate":
            engine["fragments"][1]["id"] = engine["fragments"][0]["id"]
        elif fault == "offset_bool":
            engine["fragments"][0]["offset"] = True
        else:
            raise AssertionError(fault)
        request = changed(request, body)
    rejected(lambda: api().reply_for(request))


def test_legacy_pair_does_not_silently_accept_new_context_or_version():
    _, _, request = prepared(legacy=True)
    body = json.loads(request.payload)
    body["engine_request"]["document_context"] = dict(lists=[], note_references=[])
    rejected(lambda: api().reply_for(changed(request, body)))
    del body["engine_request"]["document_context"]
    body["schema_version"] = "docx-review/2"
    rejected(lambda: api().reply_for(changed(request, body)))


def test_worker_shape_is_not_source_authority_for_a_changed_attempt_context():
    from ara.docx_analysis.storage_codec import StorageCodecError

    src, a, request = prepared()
    body = json.loads(request.payload)
    body["engine_request"]["document_context"]["lists"][0]["label"] = "999."
    fake = changed(request, body)
    # Shape-valid context alone cannot prove it came from the saved DOCX.
    reply = api().reply_for(fake)
    forged = replace(a, request_data=fake.payload, request_sha256=fake.values["request_sha256"])
    with pytest.raises(StorageCodecError) as e:
        capture_result(src, forged, reply=reply)
    assert e.value.code == "corrupt_record"
