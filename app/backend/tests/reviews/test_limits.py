"""Limits apply to the entire snapshot, including edits on unaccepted groups."""

import pytest
from pydantic import ValidationError

from ara.reviews.schemas import PutReview


@pytest.mark.parametrize("limit", ["edits", "text"])
def test_limits_are_aggregated_across_groups_and_decisions(limit):
    decisions = []
    for index, choice in enumerate(("pending", "accepted", "rejected", "deferred")):
        decisions.append(
            {
                "group_id": f" group-{index} ",
                "decision": choice,
                "edits": [
                    {"patch_index": 0, "new_block_index": block, "text": ""}
                    for block in range(1250)
                ]
                if limit == "edits"
                else [{"patch_index": 0, "new_block_index": 0, "text": "🌱" * 250_000}],
            }
        )
    payload = {
        "expected_revision_id": None,
        "expected_result_fingerprint": "ab" * 32,
        "decisions": decisions,
    }
    assert PutReview.model_validate(payload).model_dump() == payload
    if limit == "edits":
        decisions[-1]["edits"].append({"patch_index": 1, "new_block_index": 0, "text": ""})
    else:
        decisions[-1]["edits"][0]["text"] += " "
    with pytest.raises(ValidationError):
        PutReview.model_validate(payload)
