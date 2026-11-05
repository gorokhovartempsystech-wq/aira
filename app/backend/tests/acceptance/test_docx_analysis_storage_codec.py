"""Frozen B2B: canonical storage records are data, never validation capabilities."""

import json
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from uuid import UUID

import pytest
from test_docx_review_v1 import canonical, fixture, reply


def api():
    return import_module("ara.docx_analysis.storage_codec")


def execution(**changes):
    return api().ExecutionSpec(
        **(
            dict(
                execution_kind="fixture",
                engine_version="0.1.0",
                models_version="synthetic-1",
                model_sha256="1" * 64,
                adapter_sha256="2" * 64,
            )
            | changes
        )
    )


def command(s, **changes):
    return api().SavedCheckCommand(
        **(
            dict(
                document_id=s.document_id,
                registry_id=UUID(int=10),
                session_id=UUID(int=11),
                save_command_id=UUID(int=12),
                command_sequence=2,
                session_revision=0,
                storage_revision=s.storage_revision,
                source_sha256=s.source_sha256,
            )
            | changes
        )
    )


def source_bundle():
    raw, s = fixture()
    return api().capture_source(raw, s, command=command(s), execution=execution())


def result_bundle():
    source = source_bundle()
    attempt = api().prepare_attempt(source, attempt_id=UUID(int=1))
    s = api().restore_source(source).snapshot
    raw_reply = canonical(reply(s))
    result = api().capture_result(source, attempt, reply=raw_reply)
    return source, attempt, result


def reject(code, call):
    with pytest.raises(api().StorageCodecError) as caught:
        call()
    assert caught.value.code == code
    assert "Synthetic explanation" not in str(caught.value)


def test_saved_command_exact_canonical_wire_and_roundtrip():
    raw, s = fixture()
    cmd = command(s)
    encoded = api().encode_command(cmd)
    expected = dict(
        schema_version="docx-analysis-command/1",
        kind="saved",
        document_id=str(s.document_id),
        registry_id=str(UUID(int=10)),
        session_id=str(UUID(int=11)),
        save_command_id=str(UUID(int=12)),
        command_sequence="2",
        session_revision="0",
        storage_revision="7",
        source_sha256=sha256(raw).hexdigest(),
    )
    assert encoded.data == canonical(expected)
    assert encoded.sha256 == sha256(encoded.data).hexdigest()
    assert api().decode_command(encoded.data, expected_sha256=encoded.sha256) == cmd


def test_retry_command_is_distinct_and_document_bound():
    s = source_bundle()
    cmd = api().RetryCheckCommand(s.document_id, UUID(int=99))
    enc = api().encode_command(cmd)
    assert enc.data == canonical(
        dict(
            schema_version="docx-analysis-command/1",
            kind="retry",
            document_id=str(s.document_id),
            retry_of_run_id=str(UUID(int=99)),
        )
    )
    assert api().decode_command(enc.data, expected_sha256=enc.sha256) == cmd
    raw, snap = fixture()
    bundle = api().capture_source(raw, snap, command=cmd, execution=execution())
    assert api().restore_source(bundle).command == cmd


def test_execution_unicode_nul_and_exact_wire():
    spec = execution(models_version="Модель\x00😀")
    enc = api().encode_execution(spec)
    assert enc.data == canonical(
        dict(
            schema_version="docx-analysis-execution/1",
            execution_kind="fixture",
            engine_version="0.1.0",
            models_version="Модель\x00😀",
            model_sha256="1" * 64,
            adapter_sha256="2" * 64,
        )
    )
    assert api().decode_execution(enc.data, expected_sha256=enc.sha256) == spec


@pytest.mark.parametrize(
    "change",
    [
        {"command_sequence": True},
        {"session_revision": -1},
        {"storage_revision": 2**63},
        {"source_sha256": "A" * 64},
        {"document_id": "uuid"},
    ],
)
def test_command_primitives_are_strict(change):
    _, s = fixture()
    reject("invalid_input", lambda: command(s, **change))


@pytest.mark.parametrize(
    "change",
    [
        {"models_version": " "},
        {"models_version": "\ud800"},
        {"execution_kind": "cloud"},
        {"engine_version": "0.2.0"},
        {"adapter_sha256": "X" * 64},
    ],
)
def test_execution_primitives_are_strict(change):
    reject("invalid_input", lambda: execution(**change))


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b"null",
        b"\xff",
        b'{"x":NaN}',
        b'{"x":1,"x":2}',
        b'{"x":' + b"[" * 9 + b"0" + b"]" * 9 + b"}",
    ],
)
def test_malformed_storage_json_rejected(raw):
    reject(
        "corrupt_record", lambda: api().decode_command(raw, expected_sha256=sha256(raw).hexdigest())
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("storage_revision", "07"),
        ("session_revision", True),
        ("document_id", "00000000000000000000000000000001"),
        ("extra", 0),
    ],
)
def test_command_schema_is_exact(field, value):
    src = source_bundle()
    body = json.loads(src.command_data)
    body[field] = value
    raw = canonical(body)
    reject(
        "corrupt_record", lambda: api().decode_command(raw, expected_sha256=sha256(raw).hexdigest())
    )


def test_noncanonical_and_unknown_versions_are_explicit():
    src = source_bundle()
    raw = b" " + src.command_data
    reject(
        "corrupt_record", lambda: api().decode_command(raw, expected_sha256=sha256(raw).hexdigest())
    )
    body = json.loads(src.command_data)
    body["schema_version"] = "docx-analysis-command/2"
    raw = canonical(body)
    reject(
        "unsupported_version",
        lambda: api().decode_command(raw, expected_sha256=sha256(raw).hexdigest()),
    )
    reject("unsupported_version", lambda: api().restore_source(replace(src, format_version=2)))
    reject("unsupported_version", lambda: api().restore_source(replace(src, profile="other/v1")))


def test_source_manifest_is_exact_and_rebuilt_from_pinned_bytes():
    src = source_bundle()
    raw, s = fixture()
    from ara.docx_analysis.visible_main._canonical import tokens

    assert src.source_data == raw
    assert src.snapshot_data == "".join(tokens(s, omit_hash=True)).encode()
    assert src.snapshot_sha256 == sha256(src.snapshot_data).hexdigest() == s.snapshot_sha256
    restored = api().restore_source(src)
    assert restored.snapshot == s
    assert restored.command == command(s) and restored.execution == execution()


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "b" * 64},
        {"storage_revision": 8},
        {"source_data": b"other"},
        {"snapshot_sha256": "b" * 64},
        {"execution_kind": "local_model"},
        {"command_sha256": "b" * 64},
        {"storage_revision": True},
    ],
)
def test_stored_source_tampering_cannot_be_restored(change):
    src = source_bundle()
    reject("corrupt_record", lambda: api().restore_source(replace(src, **change)))


def test_rehashed_manifest_and_command_still_need_source_binding():
    src = source_bundle()
    wrong = src.snapshot_data.replace(b"abcd", b"xxxx")
    reject(
        "corrupt_record",
        lambda: api().restore_source(
            replace(src, snapshot_data=wrong, snapshot_sha256=sha256(wrong).hexdigest())
        ),
    )
    body = json.loads(src.command_data)
    body["storage_revision"] = "8"
    raw = canonical(body)
    reject(
        "corrupt_record",
        lambda: api().restore_source(
            replace(src, command_data=raw, command_sha256=sha256(raw).hexdigest())
        ),
    )


def test_attempt_and_result_restore_keep_hidden_gap_and_questions():
    src, attempt, result = result_bundle()
    envelope = api().restore_result(src, attempt, result)
    assert envelope.wire_json == result.result_data
    assert envelope.result_sha256 == result.result_sha256
    assert envelope.findings_count == 1 and envelope.questions_count == 1
    assert not envelope.no_findings
    f = json.loads(envelope.wire_json)["findings"][0]
    assert f["primary"]["quote"] == "bc" and len(f["primary"]["slices"]) == 2
    assert json.loads(attempt.request_data)["provenance"]["attempt_id"] == str(UUID(int=1))


@pytest.mark.parametrize(
    "change", [{"attempt_id": UUID(int=2)}, {"request_sha256": "b" * 64}, {"request_data": b"{}"}]
)
def test_attempt_substitution_rejected(change):
    src, a, r = result_bundle()
    reject("corrupt_record", lambda: api().restore_result(src, replace(a, **change), r))


@pytest.mark.parametrize(
    "change",
    [
        {"findings_count": 0},
        {"questions_count": 0},
        {"findings_count": False},
        {"no_findings": True},
        {"result_sha256": "b" * 64},
        {"reply_sha256": "b" * 64},
        {"reply_data": b"{}"},
    ],
)
def test_result_metadata_or_reply_substitution_rejected(change):
    src, a, r = result_bundle()
    reject("corrupt_record", lambda: api().restore_result(src, a, replace(r, **change)))


def test_rehashed_forged_result_is_not_a_validation_capability():
    src, a, r = result_bundle()
    forged = r.result_data.replace(b"Synthetic explanation", b"Changed explanation")
    assert forged != r.result_data
    reject(
        "corrupt_record",
        lambda: api().restore_result(
            src, a, replace(r, result_data=forged, result_sha256=sha256(forged).hexdigest())
        ),
    )


def test_fixture_empty_is_not_real_no_findings():
    src = source_bundle()
    a = api().prepare_attempt(src, attempt_id=UUID(int=1))
    s = api().restore_source(src).snapshot
    r = api().capture_result(src, a, reply=canonical(reply(s, issues=[])))
    assert r.findings_count == r.questions_count == 0 and r.no_findings is False


def test_reduced_caps_are_inclusive_and_revalidated():
    src = source_bundle()
    exact = api().CodecLimits(max_command_bytes=len(src.command_data))
    api().decode_command(src.command_data, expected_sha256=src.command_sha256, limits=exact)
    reject(
        "codec_limit_exceeded",
        lambda: api().decode_command(
            src.command_data,
            expected_sha256=src.command_sha256,
            limits=replace(exact, max_command_bytes=len(src.command_data) - 1),
        ),
    )
    reject(
        "codec_limit_exceeded",
        lambda: api().restore_source(src, limits=api().CodecLimits(max_fragments=1)),
    )
    reject("invalid_input", lambda: api().CodecLimits(max_source_bytes=True))
    raw, s = fixture()
    reject(
        "codec_limit_exceeded",
        lambda: api().capture_source(
            raw,
            s,
            command=command(s),
            execution=execution(),
            limits=api().CodecLimits(max_manifest_bytes=1),
        ),
    )


def test_private_bytes_and_versions_are_not_in_reprs():
    src, a, r = result_bundle()
    for obj in (src, a, r, api().restore_source(src), execution()):
        shown = repr(obj)
        assert "Synthetic explanation" not in shown and "abcd" not in shown
        assert "synthetic-1" not in shown
