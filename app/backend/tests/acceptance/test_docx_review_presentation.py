"""E1 pure presentation preserves validated findings and hides only exact issues."""

import importlib
import json
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from test_docx_analysis_storage_codec import command, execution
from test_docx_review_v1 import canonical, fixture, issue, reply
from test_docx_visible_main import GAP
from test_docx_visible_main import source as make_source

from ara.docx_analysis.storage_codec import capture_result, capture_source, prepare_attempt
from ara.docx_analysis.visible_main import build_visible_snapshot


def api():
    return importlib.import_module("ara.docx_analysis.presentation")


def bundle(*, raw=None, document_id=UUID(int=1), revision=7, spec=None, adjust=None, empty=False):
    raw = fixture()[0] if raw is None else raw
    spec = execution() if spec is None else spec
    snapshot = build_visible_snapshot(
        raw,
        document_id=document_id,
        storage_revision=revision,
        source_sha256=sha256(raw).hexdigest(),
    )
    source = capture_source(raw, snapshot, command=command(snapshot), execution=spec)
    attempt = prepare_attempt(source, attempt_id=uuid4())
    body = reply(snapshot, [] if empty else None, models=spec.models_version)
    if adjust:
        adjust(body, snapshot)
    result = capture_result(source, attempt, reply=canonical(body))
    return source, attempt, result


def key(records):
    (entry,) = api().finding_keys(*records)
    return entry.key


def view(records, **kwargs):
    result = api().present(*records, **kwargs)
    assert sha256(result.wire_json).hexdigest() == result.view_sha256
    return result, json.loads(result.wire_json)


def test_defaults_preserve_b1_addresses_and_no_private_provenance():
    records = bundle()
    result, data = view(records)
    original = json.loads(records[2].result_data)
    assert data["schema_version"] == "docx-review-view/1"
    assert data["findings"] == original["findings"]
    assert data["source"] == original["source"] and data["fixture"] is True
    assert data["stored_result_sha256"] == records[2].result_sha256
    assert data["questions"][0]["visible_finding_ids"] == original["questions"][0]["finding_ids"]
    assert data["counts"] == dict(
        total_findings=1,
        total_questions=1,
        visible_findings=1,
        visible_questions=1,
        hidden_findings=0,
        filtered_findings=0,
    )
    assert result.visible_findings == 1 and result.visible_questions == 1
    assert "private_provenance" not in data and "Synthetic" not in repr(result)
    assert api().present(*records).wire_json == result.wire_json


def test_key_stable_across_attempt_id_source_revision_and_private_noise():
    def noise(body, snapshot):
        body["issues"][0].update(id="iss-aaaaaaaaaa", confidence=0.1, suggestion=None)

    baseline = bundle()
    other = bundle(revision=8, adjust=noise)
    assert baseline[1].attempt_id != other[1].attempt_id
    assert (
        json.loads(baseline[2].result_data)["findings"][0]["finding_id"]
        != json.loads(other[2].result_data)["findings"][0]["finding_id"]
    )
    assert key(baseline) == key(other)
    assert key(baseline).startswith("dh-") and len(key(baseline)) == 67
    assert view(other, hidden_keys=[key(baseline)])[0].visible_findings == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("execution_kind", "local_model"),
        ("models_version", "synthetic-2"),
        ("model_sha256", "3" * 64),
        ("adapter_sha256", "4" * 64),
    ],
)
def test_model_identity_changes_never_inherit_hide(field, value):
    first = bundle()
    second = bundle(spec=execution(**{field: value}))
    assert key(first) != key(second)
    assert view(second, hidden_keys=[key(first)])[0].visible_findings == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("severity", "critical"),
        ("light", "red"),
        ("explanation", "New explanation"),
        ("rule", "New rule"),
        ("question", "Different?"),
    ],
)
def test_changed_issue_semantics_do_not_inherit_hide(field, value):
    def adjust(body, snapshot):
        body["issues"][0][field] = value
        body["questions"] = [body["issues"][0]["question"]]

    first, second = bundle(), bundle(adjust=adjust)
    assert key(first) != key(second)
    assert view(second, hidden_keys=[key(first)])[0].visible_findings == 1


def test_span_related_document_and_source_changes_are_distinct():
    first = bundle()

    def span(body, snapshot):
        body["issues"][0].update(span=dict(start=0, end=2, quote="ab"), suggestion=None)

    def related(body, snapshot):
        body["issues"][0].update(
            type="duplicate",
            related=dict(
                fragment_id=snapshot.fragments[1].fragment_id,
                quote=snapshot.fragments[1].text,
                status="active",
            ),
        )

    changed_raw = make_source(GAP + "<w:p><w:r><w:t>Changed 😀</w:t></w:r></w:p>")[0]
    for second in (
        bundle(adjust=span),
        bundle(adjust=related),
        bundle(document_id=uuid4()),
        bundle(raw=changed_raw),
    ):
        assert key(first) != key(second)
        assert view(second, hidden_keys=[key(first)])[0].visible_findings == 1


def test_duplicate_text_occurrences_are_not_one_hide_key():
    raw = make_source(GAP + "<w:p><w:r><w:t>abcd</w:t></w:r></w:p>")[0]

    def duplicate(body, snapshot):
        body["issues"].append(
            issue(snapshot, id="iss-aaaaaaaaaa", fragment_id=snapshot.fragments[1].fragment_id)
        )

    records = bundle(raw=raw, adjust=duplicate)
    keys = api().finding_keys(*records)
    assert len(keys) == 2 and keys[0].key != keys[1].key
    result, data = view(records, hidden_keys=[keys[0].key])
    assert result.visible_findings == 1 and data["findings"][0]["finding_id"] == keys[1].finding_id
    assert data["questions"][0]["visible_finding_ids"] == [keys[1].finding_id]
    assert len(data["questions"][0]["finding_ids"]) == 2


def test_hide_filter_restore_and_question_switch_preserve_original():
    records = bundle()
    original = records[2]
    hidden = key(records)
    result, data = view(records, hidden_keys=[hidden])
    assert result.visible_findings == 0 and result.hidden_findings == 1
    assert result.no_visible_findings is True and result.no_findings is False
    assert not data["findings"] and not data["questions"]
    assert len(data["hidden_finding_ids"]) == 1
    restored, data = view(records, hidden_keys=[hidden], show_hidden=True)
    assert restored.visible_findings == 1 and restored.visible_questions == 1
    filtered, data = view(
        records, hidden_keys=[hidden], show_hidden=True, disabled_types=["formulation"]
    )
    assert filtered.visible_findings == 0 and data["counts"]["filtered_findings"] == 1
    _, data = view(records, show_questions=False)
    assert data["findings"][0]["question"] is None and data["questions"] == []
    assert (
        records[2] == original
        and json.loads(original.result_data)["findings"][0]["question"] == "Why?"
    )


@pytest.mark.parametrize("kind", ["fixture", "local_model"])
def test_empty_validated_result_is_not_confused_with_empty_filtered_view(kind):
    records = bundle(empty=True, spec=execution(execution_kind=kind))
    result, data = view(records)
    assert result.no_findings is (kind == "local_model")
    assert result.no_visible_findings is True and data["fixture"] is (kind == "fixture")
    assert result.total_findings == 0 and data["counts"]["total_questions"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(disabled_types="formulation"),
        dict(disabled_types=["unknown"]),
        dict(disabled_types=["formulation", "formulation"]),
        dict(disabled_types=[True]),
        dict(show_questions=1),
        dict(show_hidden="true"),
        dict(hidden_keys="dh-" + "0" * 64),
        dict(hidden_keys=["dh-" + "G" * 64]),
        dict(hidden_keys=["dh-" + "0" * 64] * 2),
        dict(hidden_keys=["dh-" + f"{i:064x}" for i in range(10001)]),
    ],
)
def test_invalid_preferences_never_silently_hide_findings(kwargs):
    with pytest.raises(api().PresentationError) as caught:
        api().present(*bundle(), **kwargs)
    assert caught.value.code in ("invalid_input", "limit_exceeded")
    assert "Synthetic" not in str(caught.value)


@pytest.mark.parametrize("part", ["source", "attempt", "result", "reply", "counts"])
def test_forged_or_corrupt_records_are_revalidated(part):
    s, a, r = bundle()
    if part == "source":
        s = replace(s, source_data=b"Synthetic private")
    elif part == "attempt":
        a = replace(a, request_data=b"Synthetic private")
    elif part == "result":
        r = replace(r, result_data=b"Synthetic private")
    elif part == "reply":
        r = replace(r, reply_data=b"Synthetic private")
    else:
        r = replace(r, findings_count=99)
    for operation in (api().present, api().finding_keys):
        with pytest.raises(api().PresentationError) as caught:
            operation(s, a, r)
        assert caught.value.code == "corrupt_result" and "Synthetic" not in str(caught.value)


def test_type_filter_keeps_shared_question_with_only_visible_origins():
    def additional(body, snapshot):
        body["issues"].append(
            issue(
                snapshot,
                id="iss-aaaaaaaaaa",
                type="duplicate",
                related=dict(
                    fragment_id=snapshot.fragments[1].fragment_id,
                    quote=snapshot.fragments[1].text,
                    status="active",
                ),
            )
        )

    records = bundle(adjust=additional)
    result, data = view(records, disabled_types=["formulation"])
    assert result.total_findings == 2 and result.visible_findings == 1
    assert data["findings"][0]["type"] == "duplicate" and result.visible_questions == 1
    assert data["questions"][0]["visible_finding_ids"] == [data["findings"][0]["finding_id"]]
    assert len(data["questions"][0]["finding_ids"]) == 2


def test_changed_related_evidence_on_same_source_has_new_key():
    raw = make_source(
        GAP + "<w:p><w:r><w:t>Other</w:t></w:r></w:p>" + "<w:p><w:r><w:t>Third</w:t></w:r></w:p>"
    )[0]

    def change_related(index):
        def adjust(body, snapshot):
            body["checked"] = dict(fragments=3, active=3, skipped_status=0)
            body["issues"][0].update(
                type="duplicate",
                related=dict(
                    fragment_id=snapshot.fragments[index].fragment_id,
                    quote=snapshot.fragments[index].text,
                    status="active",
                ),
            )

        return adjust

    first = bundle(raw=raw, adjust=change_related(1))
    second = bundle(raw=raw, adjust=change_related(2))
    assert first[0].source_sha256 == second[0].source_sha256 and key(first) != key(second)
    assert view(second, hidden_keys=[key(first)])[0].visible_findings == 1
