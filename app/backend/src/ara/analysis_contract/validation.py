"""Pure validation boundaries with fixed, non-disclosing public errors."""

from collections import deque
from typing import Literal

from pydantic import BaseModel

from .models import AnalysisRequest, AnalysisResult, ValidatedAnalysis


class ContractValidationError(ValueError):
    def __init__(self, code: Literal["invalid_request", "invalid_result"]):
        self.code = code
        self.message = (
            "Invalid analysis request." if code == "invalid_request" else "Invalid analysis result."
        )
        super().__init__(self.message)


def _snapshot(value):
    """Rebuild model data, including unvalidated/mutated fields, without serialization.

    model_dump can warn with input values or serialize invalid types away. Reading
    model storage instead preserves those types for strict validation. New containers
    also detach every accepted mutable value from the caller's input.
    """
    if isinstance(value, BaseModel):
        fields = dict(value.__dict__)
        if value.__pydantic_extra__:
            fields.update(value.__pydantic_extra__)
        return {key: _snapshot(child) for key, child in fields.items()}
    if isinstance(value, dict):
        return {key: _snapshot(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_snapshot(child) for child in value]
    return value


def validate_request(payload: dict | AnalysisRequest) -> AnalysisRequest:
    try:
        if not isinstance(payload, (dict, AnalysisRequest)):
            raise ValueError("Invalid request type")
        return AnalysisRequest.model_validate(_snapshot(payload))
    except (ValueError, TypeError, RecursionError):
        raise ContractValidationError("invalid_request") from None


def _check_result(result: AnalysisResult, request: AnalysisRequest) -> None:
    if (
        result.contract_version != request.contract_version
        or result.run_id != request.run_id
        or result.base_version_id != request.base_document.version_id
        or result.context_revision_id != request.context.revision_id
    ):
        raise ValueError("Mismatched request identity")

    blocks = {block.id: block for block in request.base_document.blocks}
    sources = {("base", block.id): block.text for block in blocks.values()}
    sources.update({("context", item.id): item.text for item in request.context.items})
    coverage = {(item.source, item.id): item for item in result.coverage}
    if len(coverage) != len(result.coverage) or coverage.keys() != sources.keys():
        raise ValueError("Coverage must account for every source exactly once")
    for block in blocks.values():
        if block.kind == "unsupported" and coverage["base", block.id].status != "skipped":
            raise ValueError("Unsupported block cannot be analyzed")

    for collection in (
        result.findings,
        result.change_groups,
        result.questions,
        result.change_outcomes,
    ):
        for item in collection:
            for evidence in item.evidence:
                source = (evidence.source, evidence.id)
                if source not in sources or evidence.quote not in sources[source]:
                    raise ValueError("Invalid evidence reference or quote")

    groups = {group.id: group for group in result.change_groups}
    questions = {question.id for question in result.questions}
    dependents = {group_id: [] for group_id in groups}
    pending = {}
    for group in groups.values():
        if not set(group.blocking_question_ids) <= questions:
            raise ValueError("Unknown blocking question")
        pending[group.id] = len(group.depends_on_group_ids)
        for dependency in group.depends_on_group_ids:
            if dependency not in groups or dependency == group.id:
                raise ValueError("Invalid group dependency")
            dependents[dependency].append(group.id)
        for patch in group.patches:
            target = blocks.get(patch.target_block_id)
            if target is None:
                raise ValueError("Unknown base target")
            if target.kind == "unsupported" and patch.operation in (
                "replace_block",
                "delete_block",
            ):
                raise ValueError("Cannot overwrite unsupported block")

    # Kahn's algorithm avoids imposing Python's recursion limit on valid DAGs.
    ready = deque(group_id for group_id, count in pending.items() if count == 0)
    visited = 0
    while ready:
        group_id = ready.popleft()
        visited += 1
        for dependent in dependents[group_id]:
            pending[dependent] -= 1
            if pending[dependent] == 0:
                ready.append(dependent)
    if visited != len(groups):
        raise ValueError("Cyclic group dependencies")

    requirements = {item.id for item in request.context.items if item.role == "new_requirement"}
    outcomes = {outcome.context_item_id for outcome in result.change_outcomes}
    if outcomes != requirements or len(outcomes) != len(result.change_outcomes):
        raise ValueError("Outcomes must account for every new requirement exactly once")
    for outcome in result.change_outcomes:
        if not set(outcome.change_group_ids) <= groups.keys():
            raise ValueError("Unknown outcome group")
        if not set(outcome.question_ids) <= questions:
            raise ValueError("Unknown outcome question")
        if coverage["context", outcome.context_item_id].status == "skipped" and outcome.status in (
            "proposed",
            "already_satisfied",
        ):
            raise ValueError("Skipped requirement cannot be reported as processed")


def validate_result(
    payload: dict | AnalysisResult,
    *,
    request: dict | AnalysisRequest,
    has_import_omissions: bool = False,
) -> ValidatedAnalysis:
    parsed_request = validate_request(request)
    try:
        if type(has_import_omissions) is not bool or not isinstance(
            payload, (dict, AnalysisResult)
        ):
            raise ValueError("Invalid result or importer flag type")
        result = AnalysisResult.model_validate(_snapshot(payload))
        _check_result(result, parsed_request)
        return ValidatedAnalysis(
            result=result,
            incomplete_review=has_import_omissions
            or any(item.status == "skipped" for item in result.coverage),
        )
    except (ValueError, TypeError, RecursionError):
        raise ContractValidationError("invalid_result") from None
