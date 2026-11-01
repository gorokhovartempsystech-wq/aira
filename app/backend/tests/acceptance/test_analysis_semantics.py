"""Independent cross-reference validation for synthetic analysis examples."""

import json
from copy import deepcopy
from importlib import import_module
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"


def _example(mode="merge"):
    return tuple(
        deepcopy(json.loads((EXAMPLES / f"{mode}-{part}.json").read_text(encoding="utf-8")))
        for part in ("request", "result")
    )


def _validate(request, result, **kwargs):
    return import_module("ara.analysis_contract").validate_result(result, request=request, **kwargs)


def _reject(request, result):
    error_type = import_module("ara.analysis_contract").ContractValidationError
    with pytest.raises(error_type) as caught:
        _validate(request, result)
    assert caught.value.code == "invalid_result"


def _set(payload, path, value):
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(value)


@pytest.mark.parametrize("mode", ["merge", "lint"])
def test_saved_examples_are_valid_and_complete(mode):
    request, result = _example(mode)
    validated = _validate(request, result)
    assert validated.result.model_dump(mode="json") == result
    assert validated.incomplete_review is False


@pytest.mark.parametrize("field", ["run_id", "base_version_id", "context_revision_id"])
def test_result_must_identify_the_exact_request(field):
    request, result = _example()
    result[field] = "different-valid-id"
    _reject(request, result)


@pytest.mark.parametrize(
    "collection", ["findings", "change_groups", "questions", "change_outcomes"]
)
@pytest.mark.parametrize(("field", "value"), [("id", "unknown-id"), ("quote", "absent quotation")])
def test_every_evidence_location_checks_source_id_and_literal_quote(collection, field, value):
    request, result = _example()
    result[collection][0]["evidence"][0][field] = value
    _reject(request, result)


@pytest.mark.parametrize(
    "case", ["missing", "duplicate", "extra", "analyzed-reason", "skipped-reason", "unsupported"]
)
def test_coverage_accounts_for_exactly_the_inputs_and_real_omissions(case):
    request, result = _example()
    coverage = result["coverage"]
    if case == "missing":
        coverage.pop()
    elif case == "duplicate":
        coverage.append(deepcopy(coverage[0]))
    elif case == "extra":
        coverage.append({"source": "base", "id": "unknown", "status": "analyzed", "reason": None})
    elif case == "analyzed-reason":
        coverage[0]["reason"] = "Analyzed cannot have a skip reason"
    elif case == "skipped-reason":
        coverage[0]["status"] = "skipped"
    else:
        request["base_document"]["blocks"][3]["kind"] = "unsupported"
    _reject(request, result)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("change_groups", 0, "depends_on_group_ids"), ["g1"]),
        (("change_groups", 0, "depends_on_group_ids"), ["g2"]),
        (("change_groups", 0, "depends_on_group_ids"), ["missing"]),
        (("change_groups", 0, "blocking_question_ids"), ["missing"]),
        (("change_groups", 0, "patches", 0, "target_block_id"), "missing"),
        (("change_groups", 0, "patches", 0, "target_block_id"), "c1"),
        (("change_groups", 0, "patches", 0, "new_blocks"), []),
        (("change_groups", 1, "patches", 0, "new_blocks"), []),
        (("change_groups", 0, "patches", 0, "operation"), "delete_block"),
        (("change_groups", 0, "patches", 0, "new_blocks", 0, "kind"), "unsupported"),
        (("change_groups", 0, "patches", 0, "new_blocks", 0, "id"), "model-assigned-id"),
    ],
    ids=[
        "self-dependency",
        "cycle",
        "missing-dependency",
        "missing-blocker",
        "missing-target",
        "context-target",
        "empty-replace",
        "empty-insert",
        "delete-with-content",
        "new-unsupported",
        "new-block-id",
    ],
)
def test_patch_and_dependency_semantics(path, value):
    request, result = _example()
    _set(result, path, value)
    _reject(request, result)


@pytest.mark.parametrize("operation", ["replace_block", "delete_block"])
def test_unsupported_base_blocks_cannot_be_replaced_or_deleted(operation):
    request, result = _example()
    request["base_document"]["blocks"][3]["kind"] = "unsupported"
    result["coverage"][3].update(status="skipped", reason="Unsupported input")
    patch = result["change_groups"][0]["patches"][0]
    patch.update(operation=operation, target_block_id="b4")
    if operation == "delete_block":
        patch["new_blocks"] = []
    _reject(request, result)


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "not-new",
        "unknown-context",
        "missing-group",
        "missing-question",
        "proposed-no-group",
        "satisfied-no-base",
        "needs-no-question",
        "out-of-scope-no-reason",
    ],
)
def test_each_new_requirement_has_one_supported_outcome(case):
    request, result = _example()
    outcomes = result["change_outcomes"]
    outcome = outcomes[0]
    if case == "missing":
        outcomes.clear()
    elif case == "duplicate":
        outcomes.append(deepcopy(outcome))
    elif case in ("not-new", "unknown-context"):
        outcome["context_item_id"] = "c2" if case == "not-new" else "missing"
    elif case == "missing-group":
        outcome["change_group_ids"] = ["missing"]
    elif case == "missing-question":
        outcome["question_ids"] = ["missing"]
    elif case == "proposed-no-group":
        outcome.update(status="proposed", change_group_ids=[])
    elif case == "satisfied-no-base":
        outcome["status"] = "already_satisfied"
    elif case == "needs-no-question":
        outcome["question_ids"] = []
    else:
        outcome.update(status="out_of_scope", rationale=" ")
    _reject(request, result)


@pytest.mark.parametrize("status", ["proposed", "already_satisfied"])
def test_skipped_new_requirement_cannot_be_reported_as_processed(status):
    request, result = _example()
    result["coverage"][4].update(status="skipped", reason="New requirement not reviewed")
    outcome = result["change_outcomes"][0]
    outcome["status"] = status
    outcome["evidence"] = [deepcopy(result["findings"][0]["evidence"][0])]
    _reject(request, result)


@pytest.mark.parametrize(
    "case", ["ready-with-questions", "needs-without-questions", "repeated-contradiction"]
)
def test_question_status_and_contradiction_evidence(case):
    request, result = _example("lint")
    if case == "ready-with-questions":
        result["review_status"] = "ready"
    elif case == "needs-without-questions":
        result["questions"] = []
    else:
        finding = result["findings"][0]
        finding["category"] = "contradiction"
        finding["evidence"] = [deepcopy(finding["evidence"][0])] * 2
    _reject(request, result)


def test_same_id_in_base_and_context_is_resolved_by_source():
    request, result = _example()
    request["context"]["items"][0]["id"] = "b2"
    for coverage in result["coverage"]:
        if coverage["source"] == "context" and coverage["id"] == "c1":
            coverage["id"] = "b2"
    for collection in ("findings", "change_groups", "questions", "change_outcomes"):
        for item in result[collection]:
            for evidence in item["evidence"]:
                if evidence["source"] == "context" and evidence["id"] == "c1":
                    evidence["id"] = "b2"
    result["change_outcomes"][0]["context_item_id"] = "b2"
    assert _validate(request, result).incomplete_review is False
    result["change_groups"][1]["evidence"][0]["source"] = "base"
    _reject(request, result)  # Existing ID in the wrong namespace has different text.


def test_contradiction_can_reference_two_different_quotes_in_one_block():
    request, result = _example()
    finding = result["findings"][0]
    finding["category"] = "contradiction"
    finding["evidence"] = [
        {"source": "base", "id": "b2", "quote": quote} for quote in ("getInOuts", "name")
    ]
    assert _validate(request, result).result.findings[0].category == "contradiction"


def test_alternative_conflicting_groups_are_valid_before_selection():
    request, result = _example()
    alternative = deepcopy(result["change_groups"][0])
    alternative["id"] = "g3"
    alternative["patches"][0]["new_blocks"][0]["text"] = "Alternative replacement"
    result["change_groups"].append(alternative)
    assert len(_validate(request, result).result.change_groups) == 3


@pytest.mark.parametrize("status", ["proposed", "already_satisfied"])
def test_processed_outcomes_are_valid_with_the_required_support(status):
    request, result = _example()
    outcome = result["change_outcomes"][0]
    outcome["status"] = status
    outcome["evidence"] = [deepcopy(result["findings"][0]["evidence"][0])]
    assert _validate(request, result).result.change_outcomes[0].status == status


def test_ready_with_skips_and_importer_omissions_remains_incomplete():
    request, result = _example("lint")
    result.update(questions=[], review_status="ready")
    assert _validate(request, result).incomplete_review is False
    assert _validate(request, result, has_import_omissions=True).incomplete_review is True
    result["coverage"][0].update(status="skipped", reason="Source not fully reviewed")
    assert _validate(request, result).incomplete_review is True


def test_insert_beside_unsupported_and_question_for_skipped_requirement_are_valid():
    request, result = _example()
    request["base_document"]["blocks"][3]["kind"] = "unsupported"
    result["coverage"][3].update(status="skipped", reason="Unsupported input")
    result["change_groups"][1]["patches"][0]["target_block_id"] = "b4"
    result["coverage"][4].update(status="skipped", reason="Requires clarification")
    assert _validate(request, result).incomplete_review is True
    result["change_outcomes"][0].update(status="out_of_scope", question_ids=[], evidence=[])
    assert _validate(request, result).incomplete_review is True


def test_clean_lint_result_does_not_require_invented_findings_or_questions():
    request, result = _example("lint")
    result.update(findings=[], questions=[], change_groups=[], review_status="ready")
    checked = _validate(request, result)
    assert checked.result.model_dump(mode="json") == result
    assert checked.incomplete_review is False


@pytest.mark.parametrize("normalization", ["case", "trim", "line-endings"])
def test_evidence_must_match_without_normalizing_quote(normalization):
    request, result = _example("lint")
    evidence = result["findings"][0]["evidence"][0]
    if normalization == "case":
        evidence["quote"] = evidence["quote"].upper()
    elif normalization == "trim":
        evidence["quote"] = " " + evidence["quote"] + " "
        # The source table has spaces around its cell; use a quote with excess spacing.
        evidence["quote"] = "  " + evidence["quote"] + "  "
    else:
        evidence["quote"] = request["base_document"]["blocks"][0]["text"].replace("\n", "\r\n")
    assert evidence["quote"] not in request["base_document"]["blocks"][0]["text"]
    _reject(request, result)
