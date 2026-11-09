"""The runtime extension preserves pinned source validation and partial state."""

import pytest
from test_docx_review_v1 import fixture, issue, prepared, provenance, reply

from ara.docx_analysis.review import ReviewError
from ara.ml_review.bridge import adapt_reply


def run(payload):
    data, snapshot = fixture()
    return adapt_reply(data, snapshot, provenance(), prepared(data, snapshot), payload)


def payload():
    _, snapshot = fixture()
    raw = reply(snapshot)
    raw["partial"] = None
    raw["checked"]["pairwise"] = 2
    return raw


def test_preserve_partial_reason_and_never_report_clean():
    raw = payload()
    raw["partial"] = "Time limit: some pairs were not checked"
    result = run(raw)
    assert result["incomplete"]
    assert result["partial_reason"] == raw["partial"]
    assert result["result"]["no_findings"] is False
    assert result["checked"]["pairwise"] == 2


@pytest.mark.parametrize("pairwise", [-1, 3, True, "2"])
def test_reject_false_pairwise_coverage(pairwise):
    raw = payload()
    raw["checked"]["pairwise"] = pairwise
    with pytest.raises(ValueError):
        run(raw)


def test_reject_unknown_extension():
    raw = payload()
    raw["extra"] = 1
    with pytest.raises(ValueError):
        run(raw)


def test_still_rejects_forged_source_quote():
    _, s = fixture()
    raw = payload()
    raw["issues"] = [issue(s, span={"start": 0, "end": 4, "quote": "FAKE"})]
    with pytest.raises(ReviewError):
        run(raw)


def test_preserve_original_input():
    raw = payload()
    run(raw)
    assert "partial" in raw and "pairwise" in raw["checked"]
