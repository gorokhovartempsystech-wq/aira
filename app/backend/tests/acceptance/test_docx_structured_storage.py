"""Both fixed review profiles persist source-derived context across saved attempts."""

import json
from dataclasses import replace
from hashlib import sha256
from uuid import UUID

import pytest
from test_docx_analysis_storage_codec import api, command, execution, reject
from test_docx_review_v1 import canonical, reply
from test_docx_review_v1 import fixture as old_fixture
from test_docx_review_v2 import context, fixture


def source_bundle():
    raw, _, s = fixture()
    return api().capture_source(raw, s, command=command(s), execution=execution())


def result_bundle():
    src = source_bundle()
    s = api().restore_source(src).snapshot
    attempt = api().prepare_attempt(src, attempt_id=UUID(int=1))
    result = api().capture_result(src, attempt, reply=canonical(reply(s)))
    return src, attempt, result


def test_source_and_result_roundtrip_preserve_exact_manifest_context_and_literal_slices():
    from ara.docx_analysis.visible_lists import ListSnapshot
    from ara.docx_analysis.visible_main._canonical import tokens

    raw, _, s = fixture()
    src, attempt, result = result_bundle()
    restored = api().restore_source(src)
    assert type(restored.snapshot) is ListSnapshot and restored.snapshot == s
    assert restored.command == command(s) and restored.execution == execution()
    assert src.format_version == 1 and src.source_data == raw and src.profile == s.profile
    assert src.snapshot_data == "".join(tokens(s, omit_hash=True)).encode()
    assert src.snapshot_sha256 == sha256(src.snapshot_data).hexdigest()
    request = json.loads(attempt.request_data)
    out = json.loads(api().restore_result(src, attempt, result).wire_json)
    assert request["schema_version"] == out["schema_version"] == "docx-review/2"
    assert request["engine_request"]["document_context"] == out["document_context"] == context(s)
    assert out["findings"][0]["primary"]["quote"] == "bc"
    assert len(out["findings"][0]["primary"]["slices"]) == 2
    assert result.findings_count == result.questions_count == 1
    assert not result.no_findings


def test_retry_command_and_new_attempt_pin_the_original_profile_and_storage_revision():
    raw, _, s = fixture()
    cmd = api().RetryCheckCommand(s.document_id, UUID(int=50))
    src = api().capture_source(raw, s, command=cmd, execution=execution())
    restored = api().restore_source(src)
    assert restored.command == cmd and restored.snapshot == s
    first = api().prepare_attempt(src, attempt_id=UUID(int=1))
    second = api().prepare_attempt(src, attempt_id=UUID(int=2))
    a, b = json.loads(first.request_data), json.loads(second.request_data)
    assert a["profile"] == b["profile"] == s.profile
    assert a["source"] == b["source"] and a["snapshot_sha256"] == b["snapshot_sha256"]
    assert a["engine_request"] == b["engine_request"]
    assert first.request_sha256 != second.request_sha256


@pytest.mark.parametrize("field", ["label", "ordinal", "anchor", "remove"])
def test_rehashed_manifest_context_never_replaces_actual_source(field):
    src = source_bundle()
    body = json.loads(src.snapshot_data)
    if field == "remove":
        body["lists"] = []
    elif field == "anchor":
        body["lists"][0]["properties_anchor"] = body["lists"][0]["definition_anchor"]
    else:
        body["lists"][0][field] = "999." if field == "label" else 999
    raw = canonical(body)
    reject(
        "corrupt_record",
        lambda: api().restore_source(
            replace(src, snapshot_data=raw, snapshot_sha256=sha256(raw).hexdigest())
        ),
    )


@pytest.mark.parametrize("direction", ["old_to_new", "new_to_old"])
def test_swapping_known_profiles_is_corruption_not_an_implicit_upgrade(direction):
    from ara.docx_analysis.visible_lists._models import PROFILE as NEW
    from ara.docx_analysis.visible_main._models import PROFILE as OLD

    if direction == "old_to_new":
        raw, s = old_fixture()
        src = api().capture_source(raw, s, command=command(s), execution=execution())
        profile = NEW
    else:
        src, profile = source_bundle(), OLD
    reject("corrupt_record", lambda: api().restore_source(replace(src, profile=profile)))


@pytest.mark.parametrize(
    "field,value",
    [("format_version", 2), ("profile", "unknown/v1"), ("policy_version", "unknown/v1")],
)
def test_unknown_versions_do_not_fallback(field, value):
    src = source_bundle()
    reject("unsupported_version", lambda: api().restore_source(replace(src, **{field: value})))


@pytest.mark.parametrize("part", ["request", "result", "attempt"])
def test_rehashed_context_and_attempt_substitution_cannot_publish_or_restore(part):
    src, a, r = result_bundle()
    if part == "attempt":
        a = replace(a, attempt_id=UUID(int=99))
    else:
        raw = a.request_data if part == "request" else r.result_data
        body = json.loads(raw)
        ctx = (
            body["engine_request"]["document_context"]
            if part == "request"
            else body["document_context"]
        )
        ctx["lists"][0]["label"] = "999."
        changed = canonical(body)
        if part == "request":
            a = replace(a, request_data=changed, request_sha256=sha256(changed).hexdigest())
        else:
            r = replace(r, result_data=changed, result_sha256=sha256(changed).hexdigest())
    reject("corrupt_record", lambda: api().restore_result(src, a, r))


def test_reduced_codec_text_cap_counts_generated_labels_and_suffix():
    raw, _, s = fixture()
    cost = sum(len(f.text) for f in s.fragments) + sum(
        len(i.label) + (i.suffix != "nothing") for i in s.lists
    )
    exact = api().CodecLimits(max_text_characters=cost)
    src = api().capture_source(raw, s, command=command(s), execution=execution(), limits=exact)
    assert api().restore_source(src, limits=exact).snapshot == s
    smaller = replace(exact, max_text_characters=cost - 1)
    reject(
        "codec_limit_exceeded",
        lambda: api().capture_source(
            raw, s, command=command(s), execution=execution(), limits=smaller
        ),
    )
    reject("codec_limit_exceeded", lambda: api().restore_source(src, limits=smaller))


def test_old_source_attempt_and_result_bytes_equal_the_old_pure_protocol():
    from test_docx_review_v1 import provenance

    from ara.docx_analysis.review import prepare_review, validate_engine_reply

    raw, s = old_fixture()
    src = api().capture_source(raw, s, command=command(s), execution=execution())
    assert api().restore_source(src).snapshot == s
    attempt = api().prepare_attempt(src, attempt_id=UUID(int=1))
    request = prepare_review(raw, s, provenance=provenance())
    assert (
        attempt.request_data == request.wire_json
        and attempt.request_sha256 == request.request_sha256
    )
    raw_reply = canonical(reply(s))
    result = api().capture_result(src, attempt, reply=raw_reply)
    expected = validate_engine_reply(
        raw, s, provenance=provenance(), request=request, reply=raw_reply
    )
    assert (
        result.result_data == expected.wire_json and result.result_sha256 == expected.result_sha256
    )
    assert api().restore_result(src, attempt, result) == expected


def test_empty_fixture_result_keeps_context_but_is_not_a_real_analysis():
    src = source_bundle()
    s = api().restore_source(src).snapshot
    a = api().prepare_attempt(src, attempt_id=UUID(int=1))
    r = api().capture_result(src, a, reply=canonical(reply(s, issues=[])))
    assert r.findings_count == r.questions_count == 0 and not r.no_findings
    assert json.loads(api().restore_result(src, a, r).wire_json)["document_context"] == context(s)


def test_actual_new_aira_document_with_headings_and_two_list_instances_roundtrips():
    from test_docx_visible_lists import build

    from ara.docx_package.creation import NewParagraph, create_docx

    raw = create_docx(
        tuple(
            NewParagraph(text, style)
            for text, style in (
                ("Requirements", "heading1"),
                ("First item", "numbered"),
                ("Second item", "numbered"),
                ("Text.", "body"),
                ("Alpha", "bullet"),
                ("Beta", "bullet"),
            )
        )
    )
    s = build(raw)
    assert s.complete and len(s.lists) == 4
    src = api().capture_source(raw, s, command=command(s), execution=execution())
    restored = api().restore_source(src)
    assert restored.snapshot == s and restored.snapshot.lists == s.lists
    a = api().prepare_attempt(src, attempt_id=UUID(int=1))
    n = len(s.fragments)
    r = api().capture_result(
        src,
        a,
        reply=canonical(reply(s, issues=[], checked=dict(fragments=n, active=n, skipped_status=0))),
    )
    out = json.loads(api().restore_result(src, a, r).wire_json)
    assert out["document_context"] == context(s) and out["counts"]["fragments"] == n
