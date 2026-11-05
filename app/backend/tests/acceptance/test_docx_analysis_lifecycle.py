"""Frozen B3B: fenced claims, cancellation, deadlines and durable publication."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_analysis_runs_start import counts, start
from test_docx_analysis_runs_start import world as world
from test_docx_review_v1 import canonical, reply


def api():
    return import_module("ara.docx_analysis_runs.lifecycle")


def body(claim):
    from ara.docx_analysis.storage_codec import restore_source

    return canonical(reply(restore_source(claim.source).snapshot))


def claim(world):
    first = start(world)
    worker = uuid4()
    result = api().claim_next(world["engine"], worker_instance_id=worker)
    assert result.run_id == first.summary.run_id and result.worker_instance_id == worker
    return result


def row_count(world, table):
    with world["engine"].connect() as conn:
        return conn.scalar(text("SELECT count(*) FROM docx_analysis_" + table))


def test_claim_is_atomic_and_request_is_bound_to_attempt(world):
    c = claim(world)
    assert c.claim_fence == 1 and c.attempt.attempt_id == c.attempt_id
    assert c.source.document_id == c.document_id
    assert 0 < (c.lease_expires_at - c.claimed_at).total_seconds() <= 15
    assert api().claim_next(world["engine"], worker_instance_id=uuid4()) is None
    assert counts(world) == (1, 1) and row_count(world, "attempts") == 1


def test_concurrent_claims_have_one_winner(world):
    start(world)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(api().claim_next, world["engine"], worker_instance_id=uuid4())
            for _ in range(2)
        ]
        results = [f.result(timeout=15) for f in futures]
    assert sum(r is not None for r in results) == 1 and row_count(world, "attempts") == 1


def test_heartbeat_confirms_stage_and_cannot_regress(world):
    c = claim(world)
    ack = api().heartbeat(world["engine"], c, stage="analyzing")
    assert ack.accepted and ack.state.summary.stage == "analyzing"
    late = api().heartbeat(world["engine"], c, stage="loading_model")
    assert late.accepted and late.state.summary.stage == "analyzing"
    assert late.state.lease_expires_at <= c.deadline_at


@pytest.mark.parametrize("field", ["attempt_id", "worker_instance_id"])
def test_foreign_worker_tokens_do_not_publish_or_extend(world, field):
    c = claim(world)
    wrong = replace(c, **{field: uuid4()})
    assert not api().heartbeat(world["engine"], wrong).accepted
    assert not api().complete_attempt(world["engine"], wrong, reply=body(c)).accepted
    assert row_count(world, "results") == 0


def test_complete_publishes_result_and_same_reply_replays(world):
    c = claim(world)
    raw = body(c)
    first = api().complete_attempt(world["engine"], c, reply=raw)
    assert first.accepted and first.state.summary.status == "succeeded" and first.state.fence == 2
    again = api().complete_attempt(world["engine"], c, reply=raw)
    assert again.accepted and again.replayed and row_count(world, "results") == 1
    with world["engine"].connect() as conn:
        record = conn.execute(
            text("SELECT no_findings,findings_count,result_sha256 FROM docx_analysis_results")
        ).one()
    assert record.no_findings is False and record.findings_count == 1
    proof = api().reconcile_attempt(world["engine"], c, expected_result_sha256=record.result_sha256)
    assert proof.accepted and proof.replayed
    assert not api().complete_attempt(world["engine"], c, reply=b"{}").accepted


def test_queued_cancel_is_terminal_without_attempt(world):
    out = start(world)
    w = world["scopes"]["own"]
    state = api().cancel_run(w["runtime"], document_id=w["doc"], run_id=out.summary.run_id)
    assert state.summary.status == "cancelled" and state.fence == 1 and state.attempt_id is None
    assert api().claim_next(world["engine"], worker_instance_id=uuid4()) is None
    assert row_count(world, "attempts") == row_count(world, "results") == 0


def test_running_cancel_fences_late_reply_and_acknowledges_exit(world):
    c = claim(world)
    w = world["scopes"]["own"]
    raw = body(c)
    state = api().cancel_run(w["runtime"], document_id=w["doc"], run_id=c.run_id)
    assert state.summary.status == "cancel_requested" and state.fence == 2
    assert not api().heartbeat(world["engine"], c).accepted
    assert not api().complete_attempt(world["engine"], c, reply=raw).accepted
    ack = api().acknowledge_cancel(world["engine"], c)
    assert ack.accepted and ack.state.summary.status == "cancelled"
    assert row_count(world, "results") == 0


def test_stop_after_commit_keeps_success(world):
    c = claim(world)
    api().complete_attempt(world["engine"], c, reply=body(c))
    w = world["scopes"]["own"]
    assert (
        api().cancel_run(w["runtime"], document_id=w["doc"], run_id=c.run_id).summary.status
        == "succeeded"
    )
    assert row_count(world, "results") == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_expired_lease_is_not_restarted_or_revived(world, monkeypatch, cancelled):
    c = claim(world)
    w = world["scopes"]["own"]
    if cancelled:
        api().cancel_run(w["runtime"], document_id=w["doc"], run_id=c.run_id)
    implementation = import_module("ara.docx_analysis_runs._lifecycle")
    monkeypatch.setattr(implementation, "clock", lambda session: c.lease_expires_at)
    states = api().reap_expired(world["engine"])
    assert len(states) == 1 and states[0].summary.status == ("cancelled" if cancelled else "failed")
    if not cancelled:
        assert states[0].error_code == "interrupted"
    assert not api().heartbeat(world["engine"], c).accepted
    assert api().claim_next(world["engine"], worker_instance_id=uuid4()) is None
    assert row_count(world, "attempts") == 1


@pytest.mark.parametrize("running", [False, True])
def test_deadline_is_five_minutes_without_reset(world, monkeypatch, running):
    if running:
        c = claim(world)
        deadline = c.deadline_at
    else:
        out = start(world)
        deadline = out.summary.deadline_at
    implementation = import_module("ara.docx_analysis_runs._lifecycle")
    monkeypatch.setattr(implementation, "clock", lambda session: deadline)
    states = api().reap_expired(world["engine"])
    assert len(states) == 1 and states[0].summary.status == "timed_out"
    assert states[0].error_code == "deadline_exceeded"
    assert row_count(world, "results") == 0


def test_invalid_reply_is_failure_not_empty_success(world):
    c = claim(world)
    out = api().complete_attempt(world["engine"], c, reply=b"{}")
    assert (
        not out.accepted
        and out.state.summary.status == "failed"
        and out.state.error_code == "invalid_result"
    )
    assert row_count(world, "results") == 0


def test_source_damage_before_claim_fails_without_attempt(world):
    start(world)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_sources SET source_data=:v"), {"v": b"Damaged"})
    assert api().claim_next(world["engine"], worker_instance_id=uuid4()) is None
    with world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT error_code FROM docx_analysis_runs")) == "source_corrupt"
    assert row_count(world, "attempts") == row_count(world, "results") == 0


def test_transfer_of_ownership_prevents_worker_publication(world):
    c = claim(world)
    raw = body(c)
    w = world["scopes"]["own"]
    other = world["scopes"]["foreign"]
    with world["engine"].begin() as conn:
        conn.execute(
            text("UPDATE projects SET owner_id=:o WHERE id=:p"),
            {"o": other["runtime"].user_id, "p": w["runtime"].project_id},
        )
    out = api().complete_attempt(world["engine"], c, reply=raw)
    assert not out.accepted and out.state.error_code == "ownership_changed"
    assert row_count(world, "results") == 0


def test_fail_attempt_is_fenced_and_previous_success_survives(world):
    from test_docx_analysis_runs_start import start as again

    c = claim(world)
    api().complete_attempt(world["engine"], c, reply=body(c))
    again(world)
    second = api().claim_next(world["engine"], worker_instance_id=uuid4())
    out = api().fail_attempt(world["engine"], second, error_code="adapter_error")
    assert out.accepted and out.state.summary.status == "failed"
    assert row_count(world, "results") == 1


def test_read_state_materializes_deadline_and_is_scoped(world, monkeypatch):
    from ara.documents.storage import DocumentError

    out = start(world)
    w = world["scopes"]["own"]
    other = world["scopes"]["foreign"]
    monkeypatch.setattr(
        import_module("ara.docx_analysis_runs._lifecycle"),
        "clock",
        lambda session: out.summary.deadline_at + timedelta(seconds=1),
    )
    with pytest.raises(DocumentError) as caught:
        api().read_state(other["runtime"], document_id=w["doc"], run_id=out.summary.run_id)
    assert caught.value.status == 404
    assert (
        api()
        .read_state(w["runtime"], document_id=w["doc"], run_id=out.summary.run_id)
        .summary.status
        == "timed_out"
    )
