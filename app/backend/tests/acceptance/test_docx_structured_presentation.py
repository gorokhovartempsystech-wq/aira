"""Structured review presentation retains source context through every filter."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from test_docx_analysis_storage_codec import command, execution
from test_docx_review_presentation import bundle as legacy_bundle
from test_docx_review_v1 import canonical, issue, reply
from test_docx_review_v2 import fixture
from test_docx_visible_lists import paragraph
from test_docx_visible_unlisted import DEFS, source

from ara.docx_analysis.presentation import PresentationError, finding_keys, present
from ara.docx_analysis.storage_codec import capture_result, capture_source, prepare_attempt
from ara.docx_analysis.visible_lists import build_list_snapshot


def bundle(raw=None, *, revision=7, attempt_id=1, spec=None, empty=False, extra=False):
    raw = fixture()[0] if raw is None else raw
    s = build_list_snapshot(
        raw,
        document_id=UUID(int=1),
        storage_revision=revision,
        source_sha256=sha256(raw).hexdigest(),
    )
    spec = execution() if spec is None else spec
    src = capture_source(raw, s, command=command(s), execution=spec)
    a = prepare_attempt(src, attempt_id=UUID(int=attempt_id))
    f = s.fragments[0]
    issues = (
        [] if empty else [issue(s, span=dict(start=1, end=3, quote=f.text[1:3]), suggestion=None)]
    )
    if extra:
        issues.append(
            issue(
                s,
                id="iss-aaaaaaaaaa",
                type="duplicate",
                span=dict(start=1, end=3, quote=f.text[1:3]),
                suggestion=None,
                related=dict(
                    fragment_id=s.fragments[-1].fragment_id,
                    quote=s.fragments[-1].text,
                    status="active",
                ),
            )
        )
    body = reply(
        s,
        issues,
        models=spec.models_version,
        engine=spec.engine_version,
        checked=dict(fragments=len(s.fragments), active=len(s.fragments), skipped_status=0),
    )
    r = capture_result(src, a, reply=canonical(body))
    return src, a, r


def view(records, **kwargs):
    value = present(*records, **kwargs)
    data = json.loads(value.wire_json)
    assert value.view_sha256 == sha256(value.wire_json).hexdigest()
    assert value.wire_json == canonical(data)
    return value, data


def test_default_structured_view_preserves_all_context_and_only_source_literal_evidence():
    records = bundle()
    out, body = view(records)
    original = json.loads(records[2].result_data)
    assert body["schema_version"] == "docx-review-view/2"
    assert body["document_context"] == original["document_context"]
    assert body["document_context"]["lists"][0]["label"] == "1."
    assert body["findings"] == original["findings"]
    assert body["findings"][0]["primary"]["quote"] == "bc"
    assert len(body["findings"][0]["primary"]["slices"]) == 2
    assert body["coverage"] == original["coverage"] and body["source"] == original["source"]
    assert body["stored_result_sha256"] == records[2].result_sha256
    assert out.total_findings == out.visible_findings == 1
    assert body["fixture"] and not out.no_findings
    assert all(k not in body for k in ("private_provenance", "hidden_keys", "suggestion", "rule"))
    assert "PRIVATE" not in out.wire_json.decode() + repr(out)
    assert present(*records).wire_json == out.wire_json


@pytest.mark.parametrize("mode", ["hide", "show_hidden", "filter", "questions", "all"])
def test_filters_keep_the_complete_structured_context_and_original_records(mode):
    records = bundle(extra=True)
    original = records[2].result_data
    keys = finding_keys(*records)
    kw = dict(hidden_keys=[keys[0].key]) if mode in ("hide", "show_hidden", "all") else {}
    if mode == "show_hidden":
        kw["show_hidden"] = True
    if mode in ("filter", "all"):
        kw["disabled_types"] = ["formulation", "duplicate"]
    if mode in ("questions", "all"):
        kw["show_questions"] = False
    out, data = view(records, **kw)
    assert data["document_context"] == json.loads(original)["document_context"]
    assert records[2].result_data == original
    assert out.total_findings == 2 and out.no_findings is False
    assert out.visible_findings == (1 if mode == "hide" else 0 if mode in ("filter", "all") else 2)
    if mode == "hide":
        assert len(data["questions"][0]["finding_ids"]) == 2
        assert data["questions"][0]["visible_finding_ids"] == [keys[1].finding_id]
    if mode in ("questions", "all"):
        assert data["questions"] == [] and all(f["question"] is None for f in data["findings"])
    if mode in ("filter", "all"):
        assert out.no_visible_findings and data["findings"] == data["questions"] == []


def test_blank_list_item_is_preserved_when_it_has_no_literal_fragment_or_finding():
    raw, _ = source(paragraph("") + paragraph("abcd") + "<w:p><w:r><w:t>Other 😀</w:t></w:r></w:p>")
    records = bundle(raw)
    _, data = view(records, disabled_types=["formulation"])
    items = data["document_context"]["lists"]
    assert [i["label"] for i in items] == ["1.", "2."]
    assert items[0]["fragment_ids"] == [] and items[1]["fragment_ids"]
    assert data["findings"] == [] and data["no_findings"] is False


def test_note_links_and_split_fragments_keep_original_part_paths_when_hidden():
    from test_docx_visible_notes import fixture as note_fixture

    records = bundle(note_fixture()[0])
    _, data = view(records, hidden_keys=[finding_keys(*records)[0].key])
    expected = json.loads(records[2].result_data)["document_context"]
    assert data["document_context"] == expected
    assert len(expected["note_references"]) == 1
    link = expected["note_references"][0]
    assert link["target_anchor"]["part_name"] == "custom/Foot.xml"
    assert link["before_fragment_id"] != link["after_fragment_id"]
    assert data["findings"] == [] and data["fixture"]


@pytest.mark.parametrize("template", [False, True])
def test_no_findings_still_has_required_empty_or_nonempty_context(template):
    from ara.docx_package.creation import NewParagraph, create_docx

    raw = (
        create_docx((NewParagraph("Heading", "heading1"), NewParagraph("Body text", "body")))
        if template
        else None
    )
    records = bundle(raw, empty=True)
    out, data = view(records)
    assert data["schema_version"] == "docx-review-view/2"
    assert data["document_context"] == json.loads(records[2].result_data)["document_context"]
    assert bool(data["document_context"]["lists"]) is (not template)
    assert out.no_visible_findings and not out.no_findings and data["fixture"]


def test_same_source_across_attempt_revision_retains_keys_but_not_fragment_ids():
    old, new = bundle(), bundle(revision=8, attempt_id=2)
    a, b = finding_keys(*old)[0], finding_keys(*new)[0]
    assert a.key == b.key and a.finding_id != b.finding_id
    out, body = view(new, hidden_keys=[a.key])
    assert out.hidden_findings == 1 and out.no_visible_findings
    assert body["document_context"] == json.loads(new[2].result_data)["document_context"]


def test_changed_numbering_label_is_not_hidden_by_old_identical_literal_quote():
    old_raw, _ = source(paragraph("abcd"))
    new_raw, _ = source(paragraph("abcd"), DEFS.replace('w:val="%1."', 'w:val="Requirement %1:"'))
    old, new = bundle(old_raw), bundle(new_raw)
    assert json.loads(old[2].result_data)["findings"][0]["primary"]["quote"] == "bc"
    assert finding_keys(*old)[0].key != finding_keys(*new)[0].key
    out, body = view(new, hidden_keys=[finding_keys(*old)[0].key])
    assert (
        out.visible_findings == 1
        and body["document_context"]["lists"][0]["label"] == "Requirement 1:"
    )


def test_new_executor_never_inherits_structured_dismissal():
    old, new = bundle(), bundle(spec=execution(models_version="synthetic-2"))
    assert finding_keys(*old)[0].key != finding_keys(*new)[0].key
    assert view(new, hidden_keys=[finding_keys(*old)[0].key])[0].visible_findings == 1


def test_legacy_view_keeps_original_version_and_no_structured_property():
    _, body = view(legacy_bundle())
    assert body["schema_version"] == "docx-review-view/1" and "document_context" not in body


@pytest.mark.parametrize("part", ["source", "request", "result", "missing_context", "counts"])
def test_all_hidden_view_still_revalidates_rehashed_context_and_record_counts(part):
    records = bundle()
    key = finding_keys(*records)[0].key
    src, a, r = records
    if part == "source":
        body = json.loads(src.snapshot_data)
        body["lists"][0]["label"] = "PRIVATE"
        raw = canonical(body)
        src = replace(src, snapshot_data=raw, snapshot_sha256=sha256(raw).hexdigest())
    elif part == "request":
        body = json.loads(a.request_data)
        body["engine_request"]["document_context"]["lists"][0]["label"] = "PRIVATE"
        raw = canonical(body)
        a = replace(a, request_data=raw, request_sha256=sha256(raw).hexdigest())
    elif part == "counts":
        r = replace(r, findings_count=99)
    else:
        body = json.loads(r.result_data)
        if part == "missing_context":
            del body["document_context"]
        else:
            body["document_context"]["lists"][0]["label"] = "PRIVATE"
        raw = canonical(body)
        r = replace(r, result_data=raw, result_sha256=sha256(raw).hexdigest())
    with pytest.raises(PresentationError) as error:
        present(src, a, r, hidden_keys=[key], disabled_types=["formulation"], show_questions=False)
    assert error.value.code == "corrupt_result" and "PRIVATE" not in str(error.value)


def test_structured_context_contributes_to_output_bound_without_truncation(monkeypatch):
    from ara.docx_analysis.presentation import _view

    records = bundle()
    _, body = view(records)
    del body["document_context"]
    monkeypatch.setattr(_view, "MAX_VIEW", len(canonical(body)))
    with pytest.raises(PresentationError) as error:
        present(*records)
    assert error.value.code == "limit_exceeded"


def test_view_schema_is_closed_self_contained_and_preserves_review_evidence_types():
    s = json.loads(Path("contracts/docx-review-view-v2.json").read_text())
    review = json.loads(Path("contracts/docx-review-v2.json").read_text())
    _, body = view(bundle())
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert s["$id"] == "urn:aira:docx-review-view:2"
    assert s["additionalProperties"] is False
    assert set(s["required"]) == set(s["properties"]) == set(body)
    assert s["properties"]["schema_version"]["const"] == "docx-review-view/2"
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
        assert s["$defs"][name] == review["$defs"][name]
    q = s["$defs"]["question"]
    assert (
        set(q["required"])
        == set(q["properties"])
        == {"question_id", "text", "finding_ids", "visible_finding_ids"}
    )
    assert q["additionalProperties"] is False
    assert (
        q["properties"]["visible_finding_ids"]
        == review["$defs"]["question"]["properties"]["finding_ids"]
    )
    for name in ("counts", "preferences"):
        d = s["$defs"][name]
        assert set(d["required"]) == set(d["properties"]) == set(body[name])
        assert d["additionalProperties"] is False

    def refs(value):
        if type(value) is dict:
            if "$ref" in value:
                assert value["$ref"].startswith("#/$defs/")
                assert value["$ref"][len("#/$defs/") :] in s["$defs"]
            for item in value.values():
                refs(item)
        elif type(value) is list:
            for item in value:
                refs(item)

    refs(s)
