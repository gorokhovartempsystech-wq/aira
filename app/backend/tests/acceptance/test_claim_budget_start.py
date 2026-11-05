from types import SimpleNamespace

import pytest

from ara.docx_analysis_worker.control import make_budget
from ara.docx_analysis_worker.supervisor._attempt import claim_budget_start


def receipt(sample, replayed=False):
    return SimpleNamespace(budget_started_ns=sample, replayed=replayed)


def test_slow_preparation_does_not_spend_new_lease():
    start = claim_budget_start(0, 27_000_000_000, receipt(26_000_000_000))
    budget = make_budget(
        started_ns=start,
        received_ns=27_000_000_000,
        remaining_deadline_ns=270_000_000_000,
        remaining_lease_ns=15_000_000_000,
    )
    assert budget.lease_ns == 40_950_000_000


def test_replay_never_restarts_existing_lease():
    assert claim_budget_start(10, 100, receipt(90, True)) == 10
    assert claim_budget_start(10, 100, receipt(None)) == 10


@pytest.mark.parametrize("sample", [9, 101, True, "50"])
def test_invalid_clock_sample_rejected(sample):
    with pytest.raises(ValueError):
        claim_budget_start(10, 100, receipt(sample))
