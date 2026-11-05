"""Synthetic edge cases supplementing the independent contract acceptance gate."""

from copy import deepcopy
from traceback import format_exception

import pytest
from pydantic import ValidationError

from ara.analysis_contract import (
    AnalysisRequest,
    AnalysisResult,
    ContractValidationError,
    json_schemas,
    validate_request,
    validate_result,
)


@pytest.fixture
def pair():
    request = {
        "contract_version": "0.1.0",
        "run_id": " run ",
        "mode": "merge",
        "base_document": {
            "document_id": "doc",
            "version_id": "version",
            "blocks": [{"id": "same", "kind": "paragraph", "text": "Alpha\r\nBeta  "}],
        },
        "context": {
            "revision_id": "revision",
            "items": [{"id": "same", "role": "new_requirement", "text": "New text"}],
        },
    }
    evidence = {"source": "base", "id": "same", "quote": "\r\n"}
    result = {
        "contract_version": "0.1.0",
        "run_id": " run ",
        "base_version_id": "version",
        "context_revision_id": "revision",
        "review_status": "needs_clarification",
        "summary": "Synthetic review",
        "coverage": [
            {"source": source, "id": "same", "status": "analyzed", "reason": None}
            for source in ("base", "context")
        ],
        "findings": [
            {
                "id": "same",
                "category": "ambiguity",
                "severity": "info",
                "assessment": "needs_confirmation",
                "title": "Clarify",
                "explanation": "Unclear",
                "evidence": [deepcopy(evidence)],
            }
        ],
        "change_groups": [
            {
                "id": "same",
                "title": "Proposal",
                "basis": "design_proposal",
                "rationale": "Why",
                "evidence": [deepcopy(evidence)],
                "depends_on_group_ids": [],
                "blocking_question_ids": ["same"],
                "patches": [
                    {"operation": "delete_block", "target_block_id": "same", "new_blocks": []}
                ],
            }
        ],
        "questions": [
            {
                "id": "same",
                "prompt": "Which?",
                "reason": "Unclear",
                "evidence": [deepcopy(evidence)],
            }
        ],
        "change_outcomes": [
            {
                "context_item_id": "same",
                "status": "needs_clarification",
                "rationale": "Ask",
                "change_group_ids": ["same"],
                "question_ids": ["same"],
                "evidence": [],
            }
        ],
    }
    return request, result


def test_all_id_namespaces_are_independent_and_whitespace_quotes_are_literal(pair):
    request, result = pair
    assert validate_request(request).run_id == " run "
    assert validate_result(result, request=request).result.model_dump() == result
    result["findings"][0]["evidence"][0]["quote"] = "\nBeta "
    validate_result(result, request=request)
    result["findings"][0]["evidence"][0]["quote"] = "Alpha\nBeta"
    with pytest.raises(ContractValidationError):
        validate_result(result, request=request)


@pytest.mark.parametrize(
    "collection,field",
    [
        ("change_groups", "blocking_question_ids"),
        ("change_groups", "depends_on_group_ids"),
        ("change_outcomes", "change_group_ids"),
        ("change_outcomes", "question_ids"),
    ],
)
def test_duplicate_reference_arrays_rejected_by_models(pair, collection, field):
    _, result = pair
    result[collection][0][field] = ["same", "same"]
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(result)


@pytest.mark.parametrize("root", ["request", "result"])
@pytest.mark.parametrize("bad_version", ["0.1.1", "", 0.1, True, None])
def test_contract_version_is_exact(pair, root, bad_version):
    request, result = pair
    target = request if root == "request" else result
    target["contract_version"] = bad_version
    with pytest.raises(ContractValidationError) as caught:
        validate_result(result, request=request)
    assert caught.value.code == "invalid_" + root


@pytest.mark.parametrize("bad_text", ["\x00", "\udfff", " \ud800 ", 5, False])
def test_result_text_types_and_unicode_are_strict(pair, bad_text):
    request, result = pair
    result["change_groups"][0]["patches"][0].update(
        operation="insert_before", new_blocks=[{"kind": "code", "text": bad_text}]
    )
    with pytest.raises(ContractValidationError):
        validate_result(result, request=request)


def test_blank_new_text_and_empty_base_can_be_valid():
    request = {
        "contract_version": "0.1.0",
        "run_id": "run",
        "mode": "lint",
        "base_document": {"document_id": "doc", "version_id": "v", "blocks": []},
        "context": {"revision_id": "c", "items": []},
    }
    result = {
        "contract_version": "0.1.0",
        "run_id": "run",
        "base_version_id": "v",
        "context_revision_id": "c",
        "review_status": "ready",
        "summary": "Empty input",
        "coverage": [],
        "findings": [],
        "change_groups": [],
        "questions": [],
        "change_outcomes": [],
    }
    assert validate_result(result, request=request).incomplete_review is False


def test_blank_new_blocks_are_preserved(pair):
    request, result = pair
    result["change_groups"][0]["patches"][0].update(
        operation="replace_block",
        new_blocks=[{"kind": "paragraph", "text": text} for text in ("", " \r\n")],
    )
    assert validate_result(result, request=request).result.model_dump() == result


def test_shared_group_is_allowed_for_multiple_requirements(pair):
    request, result = pair
    request["context"]["items"].append({"id": "second", "role": "new_requirement", "text": "More"})
    result["coverage"].append(
        {"source": "context", "id": "second", "status": "analyzed", "reason": None}
    )
    result["change_outcomes"].append(
        {
            **deepcopy(result["change_outcomes"][0]),
            "context_item_id": "second",
        }
    )
    assert len(validate_result(result, request=request).result.change_outcomes) == 2


def test_long_dag_and_disconnected_cycle(pair):
    request, result = pair
    template = result["change_groups"][0]
    # Longer than Python's recursion limit, but shallow JSON and a valid DAG.
    for index in range(1500):
        result["change_groups"].append(
            {
                **deepcopy(template),
                "id": f"g{index}",
                "depends_on_group_ids": [f"g{index - 1}"] if index else [],
            }
        )
    assert len(validate_result(result, request=request).result.change_groups) == 1501
    result["change_groups"][1]["depends_on_group_ids"] = ["g1499"]
    with pytest.raises(ContractValidationError):
        validate_result(result, request=request)


@pytest.mark.parametrize("field", ["incomplete_review", "execution_mode", "confidence"])
def test_model_cannot_supply_backend_metadata(pair, field):
    request, result = pair
    result[field] = False
    with pytest.raises(ContractValidationError):
        validate_result(result, request=request)


def test_mutated_model_extra_fields_and_invalid_nested_types_are_not_serialized_away(pair):
    request, result = pair
    parsed = validate_request(request)
    object.__setattr__(parsed.context, "unexpected", "PRIVATE_MARKER")
    with pytest.raises(ContractValidationError):
        validate_request(parsed)
    parsed_result = AnalysisResult.model_validate(result)
    object.__setattr__(parsed_result, "findings", tuple(parsed_result.findings))
    with pytest.raises(ContractValidationError):
        validate_result(parsed_result, request=request)
    unvalidated = AnalysisResult.model_construct(summary="PRIVATE_MARKER")
    with pytest.raises(ContractValidationError) as caught:
        validate_result(unvalidated, request=request)
    assert "PRIVATE_MARKER" not in "".join(format_exception(caught.value))


def test_incorrect_root_and_cyclic_input_fail_safely(pair, capsys):
    request, result = pair
    for payload in (None, [], "PRIVATE_MARKER", AnalysisRequest.model_construct()):
        with pytest.raises(ContractValidationError) as caught:
            validate_result(payload, request=request)
        assert caught.value.code == "invalid_result"
        assert "PRIVATE_MARKER" not in "".join(format_exception(caught.value))
    result["findings"].append(result)
    with pytest.raises(ContractValidationError):
        validate_result(result, request=request)
    assert capsys.readouterr() == ("", "")


def test_schemas_are_fresh_detached_values():
    schemas = json_schemas()
    schemas["request"]["properties"].clear()
    assert "run_id" in json_schemas()["request"]["properties"]
