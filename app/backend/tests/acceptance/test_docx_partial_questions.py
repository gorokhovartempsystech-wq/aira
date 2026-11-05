"""Synthetic replies only: native source anchors and durable codec round trips."""

import json
from dataclasses import replace
from hashlib import sha256

import pytest
from test_docx_review_v1 import canonical
from test_docx_structured_fixture import prepared
from test_docx_visible_word import CASES, build, source

from ara.docx_analysis import storage_codec as codec
from ara.docx_analysis.presentation import present
from ara.docx_analysis.review import ReviewError
from ara.docx_analysis_worker.structured_fixture import reply_for


def setup(case="table", partial=False):
    raw = source(case)
    snapshot = build(raw)
    src, attempt, message = prepared(source=(raw, snapshot))
    reply = json.loads(reply_for(message))
    reply.update(issues=[], questions=[])
    f = snapshot.fragments[-1]
    reply["extensions"] = dict(
        schema_version="aira-review-extensions/1",
        analysis_coverage=dict(
            state="partial" if partial else "complete",
            reason="deadline" if partial else None,
            planned_checks=["formulation", "contradiction"],
            completed_checks=["formulation"] if partial else ["formulation", "contradiction"],
            pair_selection="top_k",
            pair_candidates_total=2,
            pair_candidates_completed=1 if partial else 2,
        ),
        standalone_questions=[
            dict(
                text="Какой срок выполнения?",
                reason="Учебное уточнение.",
                references=[dict(fragment_id=f.fragment_id, start=0, end=len(f.text))],
            )
        ],
    )
    return src, attempt, reply, f


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("partial", [False, True])
def test_native_mapping_roundtrip_and_public_view(case, partial):
    src, attempt, reply, fragment = setup(case, partial)
    result = codec.capture_result(src, attempt, reply=canonical(reply))
    restored = codec.restore_result(src, attempt, result)
    assert restored.wire_json == result.result_data
    body = json.loads(restored.wire_json)
    assert body["schema_version"] == "docx-review/6-draft-1"
    assert result.questions_count == 1 and not result.no_findings
    q = body["standalone_questions"][0]
    e = q["evidence"][0]
    assert e["quote"] == fragment.text and e["slices"]
    assert body["findings"] == []
    view = json.loads(present(src, attempt, result).wire_json)
    assert view["standalone_questions"] == [q]
    assert view["counts"]["visible_questions"] == 1
    assert view["analysis_coverage"]["state"] == ("partial" if partial else "complete")
    hidden = json.loads(present(src, attempt, result, show_questions=False).wire_json)
    assert hidden["standalone_questions"] == [] and hidden["counts"]["visible_questions"] == 0
    assert hidden["counts"]["total_questions"] == 1 and not hidden["no_findings"]


def test_partial_empty_is_not_clean():
    src, attempt, reply, _ = setup(partial=True)
    reply["extensions"]["standalone_questions"] = []
    result = codec.capture_result(src, attempt, reply=canonical(reply))
    assert not result.no_findings and result.questions_count == 0


@pytest.mark.parametrize(
    "patch",
    [
        dict(start=True),
        dict(end=99999),
        dict(fragment_id="missing"),
        dict(quote="invented"),
        dict(start=-1),
    ],
)
def test_reject_bad_anchor(patch):
    src, attempt, reply, _ = setup()
    reply["extensions"]["standalone_questions"][0]["references"][0].update(patch)
    with pytest.raises(ReviewError):
        codec.capture_result(src, attempt, reply=canonical(reply))


@pytest.mark.parametrize(
    "patch",
    [
        dict(reason="user"),
        dict(pair_candidates_completed=3),
        dict(pairwise=1),
        dict(completed_checks=["impact"]),
    ],
)
def test_reject_invalid_coverage(patch):
    src, attempt, reply, _ = setup(partial=True)
    reply["extensions"]["analysis_coverage"].update(patch)
    with pytest.raises(ReviewError):
        codec.capture_result(src, attempt, reply=canonical(reply))


def test_rehashed_stored_question_tamper_rejected():
    src, attempt, reply, _ = setup()
    result = codec.capture_result(src, attempt, reply=canonical(reply))
    body = json.loads(result.result_data)
    body["standalone_questions"][0]["evidence"][0]["quote"] = "invented"
    raw = canonical(body)
    tampered = replace(result, result_data=raw, result_sha256=sha256(raw).hexdigest())
    with pytest.raises(codec.StorageCodecError):
        codec.restore_result(src, attempt, tampered)


def test_duplicate_question_rejected():
    src, attempt, reply, _ = setup()
    reply["extensions"]["standalone_questions"] *= 2
    with pytest.raises(ReviewError):
        codec.capture_result(src, attempt, reply=canonical(reply))


@pytest.mark.parametrize("payload", [b"[]", b"null", b"1"])
def test_non_object_reply_is_controlled_error(payload):
    src, attempt, _, _ = setup("plain")
    with pytest.raises(ReviewError):
        codec.capture_result(src, attempt, reply=payload)


def test_extension_rejected_for_old_source_profile():
    from test_docx_review_v1 import fixture

    raw, snapshot = fixture()
    src, attempt, message = prepared(source=(raw, snapshot), legacy=True)
    reply = json.loads(reply_for(message))
    reply["extensions"] = {}
    with pytest.raises(ReviewError):
        codec.capture_result(src, attempt, reply=canonical(reply))


def test_linked_and_standalone_questions_are_counted_together():
    src, attempt, reply, _ = setup("plain")
    raw = source("plain")
    _, _, message = prepared(source=(raw, build(raw)))
    linked = json.loads(reply_for(message))
    reply.update(issues=linked["issues"], questions=linked["questions"])
    result = codec.capture_result(src, attempt, reply=canonical(reply))
    body = json.loads(result.result_data)
    assert result.questions_count == 2 and len(body["questions"]) == 1
    assert len(body["standalone_questions"]) == 1
    assert present(src, attempt, result).visible_questions == 2


def test_unicode_reference_is_codepoint_not_utf16():
    from test_docx_visible_word import W, alter

    def change(root):
        next(root.iter(W + "t")).text = "Система 😀 отвечает."

    raw = alter(source("plain"), "word/document.xml", change)
    snapshot = build(raw)
    src, attempt, message = prepared(source=(raw, snapshot))
    reply = json.loads(reply_for(message))
    _, _, template, _ = setup("plain")
    reply.update(issues=[], questions=[], extensions=template["extensions"])
    f = snapshot.fragments[0]
    start = f.text.index("😀")
    reply["extensions"]["standalone_questions"][0]["references"] = [
        dict(fragment_id=f.fragment_id, start=start, end=start + 1)
    ]
    result = codec.capture_result(src, attempt, reply=canonical(reply))
    e = json.loads(result.result_data)["standalone_questions"][0]["evidence"][0]
    assert e["quote"] == "😀" and e["end"] - e["start"] == 1
    assert e["slices"]
