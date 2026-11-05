"""Ordinary Word source proof through persisted fixture checks and public views."""

import json
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest
from test_docx_analysis_storage_codec import reject
from test_docx_review_v1 import canonical, provenance
from test_docx_structured_fixture import changed, prepared
from test_docx_visible_word import CASES, PROFILE, alter, build, source

from ara.docx_analysis import storage_codec as codec
from ara.docx_analysis.presentation import finding_keys, present
from ara.docx_analysis.remapping import match_findings
from ara.docx_analysis_worker.structured_fixture import ReviewFixtureError, reply_for


def api():
    return import_module("ara.docx_analysis.word_review")


def bundle(raw=None, revision=7):
    raw = source("numbered") if raw is None else raw
    snapshot = build(raw, storage_revision=revision)
    src, attempt, request = prepared(source=(raw, snapshot))
    return src, attempt, codec.capture_result(src, attempt, reply=reply_for(request))


@pytest.mark.parametrize("case", CASES)
def test_ordinary_package_codec_fixture_and_view_preserve_context_and_literal(case):
    raw = source(case)
    snapshot = build(raw)
    request = api().prepare_word_review(raw, snapshot, provenance=provenance())
    wire = json.loads(request.wire_json)
    assert wire["schema_version"] == "docx-review/5" and wire["profile"] == PROFILE
    assert (
        wire["engine_request"]["document_context"]["lists"]
        == json.loads(canonical(json.loads(request.engine_request_json)))["document_context"][
            "lists"
        ]
    )
    src, attempt, result = bundle(raw)
    assert src.format_version == 1 and src.source_data == raw and src.profile == PROFILE
    assert codec.restore_source(src).snapshot == snapshot
    assert codec.restore_result(src, attempt, result).wire_json == result.result_data
    body = json.loads(result.result_data)
    assert (
        body["schema_version"] == "docx-review/5"
        and body["document_context"] == wire["engine_request"]["document_context"]
    )
    assert body["findings"][0]["primary"]["quote"] in {f.text for f in snapshot.fragments}
    assert "Учебный пример" in body["findings"][0]["explanation"] and not result.no_findings
    keys = finding_keys(src, attempt, result)
    hidden = present(src, attempt, result, hidden_keys=[keys[0].key])
    view = json.loads(hidden.wire_json)
    assert (
        view["schema_version"] == "docx-review-view/5"
        and view["document_context"] == body["document_context"]
    )
    assert hidden.hidden_findings == 1 and hidden.no_visible_findings and not hidden.no_findings
    assert "private_provenance" not in view and "hidden_keys" not in view


@pytest.mark.parametrize("target", ("manifest", "request", "result", "profile"))
def test_rehashed_manifest_or_wrong_profile_cannot_replace_source(target):
    src, attempt, result = bundle()
    if target == "profile":
        src = replace(src, profile="docx-analysis/final-visible-style-lists-v1")
    else:
        data = (
            src.snapshot_data
            if target == "manifest"
            else attempt.request_data
            if target == "request"
            else result.result_data
        )
        body = json.loads(data)
        context = (
            body
            if target == "manifest"
            else body["engine_request"]["document_context"]
            if target == "request"
            else body["document_context"]
        )
        context["lists"][0]["label"] = "99."
        raw = canonical(body)
        if target == "manifest":
            src = replace(src, snapshot_data=raw, snapshot_sha256=sha256(raw).hexdigest())
        elif target == "request":
            attempt = replace(attempt, request_data=raw, request_sha256=sha256(raw).hexdigest())
        else:
            result = replace(result, result_data=raw, result_sha256=sha256(raw).hexdigest())
    reject("corrupt_record", lambda: codec.restore_result(src, attempt, result))


@pytest.mark.parametrize(
    "version,profile",
    [("docx-review/4", PROFILE), ("docx-review/5", "docx-analysis/final-visible-style-lists-v1")],
)
def test_fixture_rejects_mixed_pairs(version, profile):
    raw = source("numbered")
    _, _, message = prepared(source=(raw, build(raw)))
    body = json.loads(message.payload)
    body["schema_version"] = version
    body["profile"] = profile
    with pytest.raises(ReviewFixtureError):
        reply_for(changed(message, body))


def test_old_style_profile_hides_never_cross_into_new_word_profile():
    from test_docx_style_list_integration import bundle as old_bundle
    from test_docx_style_list_integration import fixture

    raw = fixture()[0]
    assert match_findings(old_bundle(raw), bundle(raw, revision=8)) == ()


def test_changed_auxiliary_bytes_invalidate_cross_source_hides():
    raw = source("numbered")
    old = bundle(raw)
    modified = alter(
        raw, "word/theme/theme1.xml", lambda root: root.set("name", "New synthetic theme")
    )
    assert build(modified).complete
    assert match_findings(old, bundle(modified, revision=8)) == ()


def test_closed_standalone_schemas_pin_fifth_profile_and_keep_all_required_context():
    root = Path(__file__).resolve().parents[2] / "contracts"
    schema = json.loads((root / "docx-review-v5.json").read_text())
    for shape in (schema["$defs"]["request"], schema["$defs"]["result"]):
        assert shape["properties"]["schema_version"]["const"] == "docx-review/5"
        assert shape["properties"]["profile"]["const"] == PROFILE
        assert shape["additionalProperties"] is False
    assert "document_context" in schema["$defs"]["engine_request"]["required"]
    assert "document_context" in schema["$defs"]["result"]["required"]
    view = json.loads((root / "docx-review-view-v5.json").read_text())
    assert view["properties"]["schema_version"]["const"] == "docx-review-view/5"
    assert view["properties"]["profile"]["const"] == PROFILE
    assert view["additionalProperties"] is False and "document_context" in view["required"]


def test_generated_marker_cannot_be_quoted_as_literal_text():
    raw = source("numbered")
    src, attempt, message = prepared(source=(raw, build(raw)))
    bad = json.loads(reply_for(message))
    label = json.loads(src.snapshot_data)["lists"][0]["label"]
    bad["issues"][0]["span"] = dict(start=0, end=len(label), quote=label)
    with pytest.raises(api().ReviewError) as exc:
        codec.capture_result(src, attempt, reply=canonical(bad))
    assert exc.value.code == "invalid_reply"


@pytest.mark.parametrize("kind", ("aira", "plain"))
def test_new_document_and_plain_file_always_use_new_source_policy(kind):
    from test_docx_structured_runtime import created

    raw = created() if kind == "aira" else source("plain")
    src, attempt, result = bundle(raw)
    assert (
        src.profile == PROFILE
        and json.loads(result.result_data)["schema_version"] == "docx-review/5"
    )
    assert (
        json.loads(present(src, attempt, result).wire_json)["schema_version"]
        == "docx-review-view/5"
    )


def test_distant_text_change_preserves_new_profile_hide():
    from test_docx_style_list_integration import fixture

    old = bundle(fixture()[0])
    new = bundle(fixture(intro="Changed distant intro")[0], revision=8)
    transfers = match_findings(old, new)
    assert len(transfers) == 1
    assert present(*new, hidden_keys=[transfers[0].current_key]).no_visible_findings


def test_word_codec_bounds_generated_label_work_in_capture_and_restore():
    from test_docx_analysis_storage_codec import command
    from test_docx_style_list_integration import fixture

    from ara.docx_analysis_worker.structured_fixture import fixture_execution

    raw = fixture()[0]
    snapshot = build(raw)
    cost = sum(len(f.text) for f in snapshot.fragments) + sum(
        len(i.label) + (i.suffix != "nothing") for i in snapshot.lists
    )
    limits = codec.CodecLimits(max_text_characters=cost)
    src = codec.capture_source(
        raw, snapshot, command=command(snapshot), execution=fixture_execution(), limits=limits
    )
    assert codec.restore_source(src, limits=limits).snapshot == snapshot
    reject(
        "codec_limit_exceeded",
        lambda: codec.restore_source(src, limits=replace(limits, max_text_characters=cost - 1)),
    )


@pytest.mark.parametrize("hidden", [False, True])
def test_word_resolution_work_budget_includes_generated_labels(hidden):
    from test_docx_structured_remapping import resolution_input
    from test_docx_style_list_integration import fixture

    from ara.documents.storage import DocumentError
    from ara.docx_review_resolution._resolve import resolve

    raw = fixture()[0]
    old, new = bundle(raw), bundle(raw, revision=8)
    snapshot = json.loads(new[0].snapshot_data)
    cost = len(snapshot["analysis_text"]) + sum(
        len(i["label"]) + (i["suffix"] != "nothing") for i in snapshot["lists"]
    )
    passes = 3 if hidden else 1
    inputs = resolution_input(old, new, limit=passes * cost, hidden=hidden)
    result = resolve(inputs)
    assert bool(result.hidden_keys) is hidden and result.decisions == inputs.decisions
    with pytest.raises(DocumentError) as exc:
        resolve(resolution_input(old, new, limit=passes * cost - 1, hidden=hidden))
    assert exc.value.code == "preferences_resolution_limit" and exc.value.status == 413


@pytest.mark.parametrize("field", ["style_chain", "properties_anchor", "extra"])
def test_fifth_fixture_keeps_closed_style_provenance_validation(field):
    from test_docx_style_list_integration import fixture

    raw = fixture()[0]
    _, _, message = prepared(source=(raw, build(raw)))
    body = json.loads(message.payload)
    item = next(i for i in body["engine_request"]["document_context"]["lists"] if i["style_chain"])
    item[field] = [] if field == "style_chain" else item["paragraph_anchor"]
    with pytest.raises(ReviewFixtureError):
        reply_for(changed(message, body))
