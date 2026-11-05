"""Additional lifecycle edges beyond the frozen C1A acceptance matrix."""

from dataclasses import replace
from uuid import UUID

import pytest

from ara.docx_analysis_worker.control import (
    AttemptControl,
    AttemptIdentity,
    Budget,
    ControlError,
    make_budget,
)


def control():
    return AttemptControl(
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1), Budget(100, 15, 0, 0)
    )


def test_control_detaches_original_and_returned_identity():
    i = AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1)
    c = AttemptControl(i, Budget(100, 15, 0, 0))
    object.__setattr__(i, "claim_fence", 2)
    object.__setattr__(c.view().identity, "attempt_id", UUID(int=99))
    assert c.view().identity.claim_fence == 1
    assert c.view().identity.attempt_id == UUID(int=2)


def test_ack_is_clamped_to_original_deadline_and_guard_not_accumulated():
    c = AttemptControl(
        AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1),
        make_budget(
            started_ns=0,
            received_ns=0,
            remaining_deadline_ns=500_000_000,
            remaining_lease_ns=500_000_000,
        ),
    )
    v = c.acknowledge_lease(
        started_ns=100_000_000, received_ns=200_000_000, remaining_lease_ns=15_000_000_000
    )
    assert v.deadline_ns == v.lease_ns == 450_000_000
    assert c.tick(now_ns=449_999_999).phase == "open"
    assert c.tick(now_ns=450_000_000).stop_reason == "deadline"


@pytest.mark.parametrize("outcome", ["unknown", "committed", "terminal"])
def test_no_renewal_after_publication_admission(outcome):
    c = control()
    c.mark_child_closed(now_ns=0)
    p = c.reserve(now_ns=0)
    c.settle(p, outcome=outcome, now_ns=1)
    assert c.acknowledge_lease(started_ns=1, received_ns=2, remaining_lease_ns=1_000).lease_ns == 15


def test_backward_clock_cannot_hide_committed_fact():
    c = control()
    c.mark_child_closed(now_ns=5)
    p = c.reserve(now_ns=5)
    assert c.settle(p, outcome="committed", now_ns=3).phase == "succeeded"
    assert c.view().last_ns == 5


def test_repeated_rollback_generations_never_reauthorize_old_permits():
    c = control()
    c.mark_child_closed(now_ns=0)
    first = c.reserve(now_ns=0)
    c.settle(first, outcome="rolled_back", now_ns=0)
    for _ in range(1000):
        p = c.reserve(now_ns=0)
        with pytest.raises(ControlError, match="invalid_permit"):
            c.settle(first, outcome="committed", now_ns=0)
        c.settle(p, outcome="rolled_back", now_ns=0)
    c.request_stop(now_ns=0)
    assert c.reserve(now_ns=0) is None


def test_missing_fields_in_constructor_bypass_do_not_escape_as_attribute_errors():
    for value in (object.__new__(Budget), replace(Budget(100, 10, 0, 0), last_ns=None)):
        with pytest.raises(ControlError):
            AttemptControl(AttemptIdentity(UUID(int=1), UUID(int=2), UUID(int=3), 1), value)
