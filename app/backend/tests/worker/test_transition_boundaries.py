"""Worker regression tests using synthetic inputs and disposable PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from ara import worker
from ara.documents.storage import DocumentError
from ara.worker import execution
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world


def enqueue(world):
    with world["client"]() as client:
        response = client.post(
            f"/documents/{world['documents']['own']['id']}/runs",
            json=world["body"],
            headers={"Idempotency-Key": uuid4().hex},
        )
    assert response.status_code == 202
    return UUID(response.json()["run_id"])


def snapshot(engine, run_id):
    with engine.connect() as connection:
        return tuple(
            [dict(row) for row in connection.execute(text(query), {"id": run_id}).mappings()]
            for query in (
                "SELECT * FROM analysis_runs WHERE id = :id",
                "SELECT * FROM analysis_attempts WHERE run_id = :id ORDER BY attempt_number",
            )
        )


@pytest.mark.parametrize("invalid", [False, True])
def test_validation_time_does_not_extend_lease(run_world, monkeypatch, invalid):
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    claim = worker.claim_next(engine, settings=worker.WorkerSettings(lease_seconds=1))
    before = snapshot(engine, run_id)
    original = execution.validate_result

    def slow_validation(*args, **kwargs):
        with engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM "
                    "(CAST(:expiry AS timestamptz) - clock_timestamp()))) "
                    "::double precision + 0.05)"
                ),
                {"expiry": claim.lease_expires_at},
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(execution, "validate_result", slow_validation)
    payload = {} if invalid else worker.fixture_result(claim.request)
    assert worker.complete_attempt(engine, claim, payload) is False
    assert snapshot(engine, run_id) == before


def test_workers_on_same_document_keep_distinct_attempts_without_deadlock(run_world):
    engine = run_world["engine"]
    run_ids = {enqueue(run_world), enqueue(run_world)}
    barrier = Barrier(2)

    def meet_after_scope_locks(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO analysis_attempts"):
            barrier.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", meet_after_scope_locks)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker.run_once, engine) for _ in range(2)]
            outcomes = [future.result(timeout=10) for future in futures]
    finally:
        event.remove(engine, "before_cursor_execute", meet_after_scope_locks)
    assert {outcome.run_id for outcome in outcomes} == run_ids
    assert all(outcome.outcome == "succeeded" for outcome in outcomes)
    for run_id in run_ids:
        rows, history = snapshot(engine, run_id)
        assert rows[0]["attempt_count"] == 1
        assert len(history) == 1 and history[0]["status"] == "succeeded"


def test_corrupt_request_is_terminalized_without_calling_adapter(run_world):
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE analysis_runs SET request_payload = '{}'::jsonb WHERE id = :id"),
            {"id": run_id},
        )

    def forbidden(request):
        pytest.fail("Invalid snapshot reached adapter")

    assert worker.run_once(engine, adapter=forbidden).outcome == "idle"
    rows, history = snapshot(engine, run_id)
    assert rows[0]["status"] == "failed" and rows[0]["error_code"] == "invalid_request"
    assert rows[0]["result_payload"] is None and history == []


def test_access_revocation_terminalizes_even_a_future_retry(run_world):
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    claim = worker.claim_next(engine, settings=worker.WorkerSettings(retry_delay_seconds=60))
    assert worker.fail_attempt(engine, claim, code="adapter_error")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE documents SET project_id = :project WHERE id = :id"),
            {
                "project": run_world["projects"]["foreign"],
                "id": UUID(run_world["documents"]["own"]["id"]),
            },
        )
    assert worker.claim_next(engine) is None
    rows, history = snapshot(engine, run_id)
    assert rows[0]["error_code"] == "access_revoked" and rows[0]["status"] == "failed"
    assert len(history) == 1 and history[0]["error_code"] == "adapter_error"


def test_result_storage_failure_is_not_an_adapter_retry(run_world):
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    calls = []

    def fail_commit(connection):
        raise OperationalError("Synthetic database failure", {}, Exception("Synthetic"))

    def adapter(request):
        calls.append(request.run_id)
        # Claim has already committed; only completion now encounters this failure.
        event.listen(engine, "commit", fail_commit)
        return worker.fixture_result(request)

    try:
        with pytest.raises(DocumentError) as caught:
            worker.run_once(engine, adapter=adapter)
    finally:
        event.remove(engine, "commit", fail_commit)
    assert (caught.value.code, caught.value.retryable) == ("storage_unavailable", True)
    assert calls == [str(run_id)]
    rows, history = snapshot(engine, run_id)
    assert rows[0]["status"] == "running" and rows[0]["result_payload"] is None
    assert len(history) == 1 and history[0]["status"] == "running"
