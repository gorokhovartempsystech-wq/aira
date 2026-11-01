"""Pure text-transfer demonstration; no semantic analysis or external calls."""

from ara.analysis_contract import AnalysisRequest, validate_request


def fixture_result(request: AnalysisRequest | dict) -> dict:
    request = validate_request(request)
    result = {
        "contract_version": request.contract_version,
        "run_id": request.run_id,
        "base_version_id": request.base_document.version_id,
        "context_revision_id": request.context.revision_id,
        "review_status": "ready",
        "summary": "fixture: deterministic text-transfer demonstration; meaning was not analyzed.",
        "coverage": [],
        "findings": [],
        "change_groups": [],
        "questions": [],
        "change_outcomes": [],
    }
    anchor = None
    for block in request.base_document.blocks:
        skipped = block.kind == "unsupported"
        result["coverage"].append(
            {
                "source": "base",
                "id": block.id,
                "status": "skipped" if skipped else "analyzed",
                "reason": "fixture cannot process unsupported blocks" if skipped else None,
            }
        )
        if not skipped:
            anchor = block.id
    for number, item in enumerate(request.context.items, 1):
        empty = item.text == ""
        result["coverage"].append(
            {
                "source": "context",
                "id": item.id,
                "status": "skipped" if empty else "analyzed",
                "reason": "fixture cannot process empty context" if empty else None,
            }
        )
        if item.role != "new_requirement":
            continue
        evidence = [] if empty else [{"source": "context", "id": item.id, "quote": item.text}]
        outcome = {
            "context_item_id": item.id,
            "status": "out_of_scope",
            "rationale": "fixture cannot transfer an empty requirement",
            "change_group_ids": [],
            "question_ids": [],
            "evidence": evidence,
        }
        if not empty and anchor is not None:
            group_id = f"fixture-group-{number}"
            result["change_groups"].append(
                {
                    "id": group_id,
                    "title": "fixture text transfer",
                    "basis": "explicit_requirement",
                    "rationale": "Demonstration only; placement and meaning not analyzed.",
                    "evidence": evidence,
                    "depends_on_group_ids": [],
                    "blocking_question_ids": [],
                    "patches": [
                        {
                            "operation": "insert_after",
                            "target_block_id": anchor,
                            "new_blocks": [{"kind": "paragraph", "text": item.text}],
                        }
                    ],
                }
            )
            outcome.update(
                status="proposed",
                change_group_ids=[group_id],
                rationale="fixture transfers the exact requirement text",
            )
        elif not empty:
            question_id = f"fixture-question-{number}"
            result["questions"].append(
                {
                    "id": question_id,
                    "prompt": "Provide a supported insertion anchor.",
                    "reason": "fixture has no supported base block for its demonstration insertion",
                    "evidence": evidence,
                }
            )
            result["review_status"] = "needs_clarification"
            outcome.update(
                status="needs_clarification",
                question_ids=[question_id],
                rationale="fixture requires a supported insertion anchor",
            )
        result["change_outcomes"].append(outcome)
    return result
