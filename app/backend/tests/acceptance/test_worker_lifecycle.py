"""Independent worker lifecycle and fencing acceptance on disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from importlib import import_module
from threading import Barrier, Event, get_ident
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

PRIVATE = "SYNTHETIC_PRIVATE_WORKER_630"


def worker():
    return import_module("ara.worker")


def enqueue(world):
    with world["client"]() as client:
        response = client.post(
            f"/documents/{world['documents']['own']['id']}/runs",
            json=world["body"],
            headers={"Idempotency-Key": "worker-" + uuid4().hex},
        )
    assert response.status_code == 202, response.text
    return UUID(response.json()["run_id"])


def run_row(engine, run_id):
    with engine.connect() as connection:
        return dict(
            connection.execute(text("SELECT * FROM analysis_runs WHERE id = :id"), {"id": run_id})
            .mappings()
            .one()
        )


def attempts(engine, run_id):
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM analysis_attempts WHERE run_id = :id ORDER BY attempt_number"),
                {"id": run_id},
            ).mappings()
        ]


def state(engine, run_id):
    return run_row(engine, run_id), attempts(engine, run_id)


def expire_lease(engine, run_id, *, deadline=False):
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE analysis_runs SET lease_expires_at = clock_timestamp() - interval '2s' "
                "WHERE id = :id"
            ),
            {"id": run_id},
        )
        connection.execute(
            text(
                "UPDATE analysis_attempts SET lease_expires_at = "
                "(SELECT lease_expires_at FROM analysis_runs WHERE id = :id) "
                "WHERE id = (SELECT active_attempt_id FROM analysis_runs WHERE id = :id)"
            ),
            {"id": run_id},
        )
        if deadline:
            connection.execute(
                text(
                    "UPDATE analysis_runs SET deadline_at = clock_timestamp() - interval '1s' "
                    "WHERE id = :id"
                ),
                {"id": run_id},
            )


def assert_failed(engine, run_id, code):
    row = run_row(engine, run_id)
    assert row["status"] == "failed"
    assert row["error_code"] == code
    assert row["completed_at"] is not None
    assert row["result_payload"] is None and row["incomplete_review"] is None
    assert row["active_attempt_id"] is None and row["lease_expires_at"] is None
    return row


def safe_storage_failure(operation, status=503, code="storage_unavailable", retryable=True):
    error_type = import_module("ara.documents.api").DocumentError
    with pytest.raises(error_type) as caught:
        operation()
    error = caught.value
    assert (error.status, error.code, error.retryable) == (status, code, retryable)
    assert PRIVATE not in str(error) + repr(error) + error.message
    assert error.__cause__ is None
    assert error.__suppress_context__ or error.__context__ is None


@contextmanager
def bounded_connections(engine):
    def bound(connection, record):
        previous = connection.autocommit
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '2s'")
                cursor.execute("SET statement_timeout = '5s'")
        finally:
            connection.autocommit = previous

    event.listen(engine, "connect", bound)
    try:
        yield
    finally:
        event.remove(engine, "connect", bound)


def test_concurrent_claims_cannot_own_the_same_run(run_world):
    api = worker()
    world = run_world
    engine = world["engine"]
    run_id = enqueue(world)
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        return api.claim_next(engine)

    with bounded_connections(engine), ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim) for _ in range(2)]
        claimed = [future.result(timeout=10) for future in futures]
    winners = [claim for claim in claimed if claim is not None]
    assert len(winners) == 1
    claim = winners[0]
    assert claim.run_id == run_id and claim.attempt_number == 1
    assert claim.lease_expires_at.utcoffset() is not None
    assert claim.deadline_at.utcoffset() is not None
    row, history = state(engine, run_id)
    assert row["status"] == "running" and row["attempt_count"] == 1
    assert row["active_attempt_id"] == claim.attempt_id
    assert len(history) == 1 and history[0]["id"] == claim.attempt_id
    assert history[0]["project_id"] == world["projects"]["own"]


def test_claim_skips_a_locked_earlier_run_instead_of_waiting(run_world):
    api = worker()
    engine = run_world["engine"]
    first, second = enqueue(run_world), enqueue(run_world)
    with bounded_connections(engine), ThreadPoolExecutor(max_workers=1) as executor:
        # The transaction releases its lock before executor shutdown, including on failure.
        with engine.begin() as connection:
            connection.execute(
                text("SELECT id FROM analysis_runs WHERE id = :id FOR UPDATE"), {"id": first}
            )
            future = executor.submit(api.claim_next, engine)
            claim = future.result(timeout=8)
            assert claim is not None and claim.run_id == second
    assert run_row(engine, first)["status"] == "queued"
    assert attempts(engine, first) == []
    assert api.claim_next(engine).run_id == first


def test_expired_attempt_and_all_stale_writes_cannot_change_its_successor(run_world):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    first = api.claim_next(engine)
    first_payload = api.fixture_result(first.request)
    expire_lease(engine, run_id)
    expired = state(engine, run_id)
    assert api.complete_attempt(engine, first, first_payload) is False
    assert api.fail_attempt(engine, first, code="adapter_error") is False
    assert state(engine, run_id) == expired
    second = api.claim_next(engine)
    assert second.attempt_id != first.attempt_id and second.attempt_number == 2
    history = attempts(engine, run_id)
    assert history[0]["status"] == "expired" and history[0]["error_code"] == "lease_expired"
    assert history[0]["finished_at"] is not None
    assert history[1]["status"] == "running"
    before = state(engine, run_id)
    assert api.complete_attempt(engine, first, first_payload) is False
    assert api.complete_attempt(engine, first, {"invalid": PRIVATE}) is False
    assert api.fail_attempt(engine, first, code="invalid_result") is False
    assert state(engine, run_id) == before
    assert api.complete_attempt(engine, second, api.fixture_result(second.request)) is True
    terminal = state(engine, run_id)
    assert terminal[0]["status"] == "succeeded"
    assert api.complete_attempt(engine, first, first_payload) is False
    assert api.fail_attempt(engine, first, code="adapter_timeout") is False
    assert state(engine, run_id) == terminal


def test_completion_uses_fresh_database_clock_after_waiting_for_a_lock(run_world):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    claim = api.claim_next(engine, settings=api.WorkerSettings(lease_seconds=1))
    payload = api.fixture_result(claim.request)
    before = state(engine, run_id)
    started = Event()
    calling_thread = get_ident()

    def observe(connection, cursor, statement, parameters, context, executemany):
        if get_ident() != calling_thread:
            started.set()

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with bounded_connections(engine), ThreadPoolExecutor(max_workers=1) as executor:
            with engine.begin() as connection:
                connection.execute(
                    text("SELECT id FROM analysis_runs WHERE id = :id FOR UPDATE"), {"id": run_id}
                )
                future = executor.submit(api.complete_attempt, engine, claim, payload)
                assert started.wait(timeout=1)
                now = connection.scalar(text("SELECT clock_timestamp()"))
                assert now < claim.lease_expires_at, "Completion must start while its lease is live"
                connection.execute(
                    text(
                        "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM "
                        "(CAST(:expiry AS timestamptz) - clock_timestamp())))"
                        "::double precision + 0.1)"
                    ),
                    {"expiry": claim.lease_expires_at},
                )
                assert not future.done(), "Completion must wait for the run lock"
            assert future.result(timeout=5) is False
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert state(engine, run_id) == before


@pytest.mark.parametrize("reason", ["deadline_exceeded", "attempts_exhausted"])
def test_polling_terminalizes_expired_runs_without_resetting_their_budget(run_world, reason):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    settings = api.WorkerSettings(max_attempts=1 if reason == "attempts_exhausted" else 3)
    api.claim_next(engine, settings=settings)
    expire_lease(engine, run_id, deadline=reason == "deadline_exceeded")
    changed_policy = api.WorkerSettings(max_attempts=10, run_timeout_seconds=86400)
    assert api.claim_next(engine, settings=changed_policy) is None
    row = assert_failed(engine, run_id, reason)
    assert row["attempt_count"] == 1 and row["max_attempts"] == settings.max_attempts
    history = attempts(engine, run_id)
    assert len(history) == 1 and history[0]["status"] == "expired"
    assert history[0]["error_code"] == "lease_expired"


def test_backoff_and_first_claim_policy_survive_new_worker_settings(run_world):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    settings = api.WorkerSettings(max_attempts=2, run_timeout_seconds=300, retry_delay_seconds=60)
    first = api.claim_next(engine, settings=settings)
    initial = run_row(engine, run_id)
    with engine.connect() as connection:
        before = connection.scalar(text("SELECT clock_timestamp()"))
    assert api.fail_attempt(engine, first, code="adapter_error") is True
    with engine.connect() as connection:
        after = connection.scalar(text("SELECT clock_timestamp()"))
    queued = run_row(engine, run_id)
    assert queued["status"] == "queued" and queued["attempt_count"] == 1
    assert queued["active_attempt_id"] is None and queued["error_code"] is None
    assert before + timedelta(seconds=60) <= queued["available_at"] <= after + timedelta(seconds=60)
    assert attempts(engine, run_id)[0]["retry_delay_seconds"] == 60
    newer = api.WorkerSettings(max_attempts=10, run_timeout_seconds=86400, retry_delay_seconds=0)
    assert api.claim_next(engine, settings=newer) is None
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE analysis_runs SET available_at = clock_timestamp() - interval '1s' "
                "WHERE id = :id"
            ),
            {"id": run_id},
        )
    second = api.claim_next(engine, settings=newer)
    assert second.attempt_number == 2 and second.attempt_id != first.attempt_id
    row = run_row(engine, run_id)
    assert row["max_attempts"] == 2 and row["deadline_at"] == initial["deadline_at"]
    assert api.fail_attempt(engine, second, code="adapter_error") is True
    assert_failed(engine, run_id, "attempts_exhausted")


def test_deadline_expires_even_when_retry_is_not_yet_available(run_world):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    claim = api.claim_next(
        engine, settings=api.WorkerSettings(run_timeout_seconds=300, retry_delay_seconds=60)
    )
    assert api.fail_attempt(engine, claim, code="adapter_timeout") is True
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE analysis_runs SET deadline_at = clock_timestamp() - interval '1s' "
                "WHERE id = :id"
            ),
            {"id": run_id},
        )
    assert api.claim_next(engine) is None
    assert_failed(engine, run_id, "deadline_exceeded")
    assert len(attempts(engine, run_id)) == 1


def test_lease_is_clamped_and_retry_cannot_outlive_the_deadline(run_world):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    claim = api.claim_next(
        engine,
        settings=api.WorkerSettings(
            lease_seconds=300, run_timeout_seconds=10, retry_delay_seconds=10
        ),
    )
    assert claim.lease_expires_at == claim.deadline_at
    assert api.fail_attempt(engine, claim, code="adapter_timeout") is True
    assert_failed(engine, run_id, "deadline_exceeded")
    assert attempts(engine, run_id)[0]["error_code"] == "adapter_timeout"


@pytest.mark.parametrize("change", ["owner", "project"])
def test_revoked_access_before_claim_never_reaches_adapter(run_world, change):
    api = worker()
    world = run_world
    engine = world["engine"]
    run_id = enqueue(world)
    with engine.begin() as connection:
        if change == "owner":
            connection.execute(
                text("UPDATE projects SET owner_id = :owner WHERE id = :id"),
                {"owner": world["owners"]["foreign"], "id": world["projects"]["own"]},
            )
        else:
            connection.execute(
                text("UPDATE documents SET project_id = :project WHERE id = :id"),
                {
                    "project": world["projects"]["foreign"],
                    "id": UUID(world["documents"]["own"]["id"]),
                },
            )

    def forbidden(request):
        pytest.fail("Worker passed a revoked source to the adapter")

    outcome = api.run_once(engine, adapter=forbidden)
    assert outcome.outcome == "idle" and outcome.run_id is None
    row = assert_failed(engine, run_id, "access_revoked")
    assert row["attempt_count"] == 0 and attempts(engine, run_id) == []


@pytest.mark.parametrize("change", ["owner", "project"])
@pytest.mark.parametrize("operation", ["complete", "fail"])
def test_live_attempt_loses_access_on_owner_or_project_change(run_world, change, operation):
    api = worker()
    world = run_world
    engine = world["engine"]
    run_id = enqueue(world)
    claim = api.claim_next(engine)
    payload = api.fixture_result(claim.request)
    with engine.begin() as connection:
        if change == "owner":
            connection.execute(
                text("UPDATE projects SET owner_id = :owner WHERE id = :id"),
                {"owner": world["owners"]["foreign"], "id": world["projects"]["own"]},
            )
        else:
            # Moving to another project of the SAME owner must still fence this attempt.
            connection.execute(
                text("UPDATE documents SET project_id = :project WHERE id = :id"),
                {"project": world["projects"]["peer"], "id": UUID(world["documents"]["own"]["id"])},
            )
    if operation == "complete":
        assert api.complete_attempt(engine, claim, payload) is False
    else:
        assert api.fail_attempt(engine, claim, code="adapter_error") is True
    assert_failed(engine, run_id, "access_revoked")
    history = attempts(engine, run_id)
    assert history[0]["status"] == "failed" and history[0]["error_code"] == "access_revoked"


def test_completion_uses_saved_request_and_importer_flag_not_mutated_claim(run_world):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE analysis_runs SET has_import_omissions = true WHERE id = :id"),
            {"id": run_id},
        )
    claim = api.claim_next(engine)
    original = deepcopy(run_row(engine, run_id)["request_payload"])
    object.__setattr__(claim.request.context.items[0], "text", PRIVATE)
    object.__setattr__(claim, "has_import_omissions", False)
    object.__setattr__(claim, "attempt_number", 999)
    assert api.complete_attempt(engine, claim, api.fixture_result(original)) is True
    row = run_row(engine, run_id)
    assert row["status"] == "succeeded" and row["incomplete_review"] is True
    assert row["request_payload"] == original
    assert row["result_payload"]["run_id"] == str(run_id)


def test_adapter_runs_after_commit_without_locks_and_needs_clarification_is_success(run_world):
    api = worker()
    world = run_world
    engine = world["engine"]
    run_id = enqueue(world)
    original = deepcopy(run_row(engine, run_id)["request_payload"])
    calls = []

    def adapter(request):
        calls.append(request.model_dump(mode="json"))
        with engine.begin() as connection:
            for table, row_id in (
                ("analysis_runs", run_id),
                ("projects", world["projects"]["own"]),
                ("documents", UUID(world["documents"]["own"]["id"])),
            ):
                connection.execute(
                    text(f"SELECT id FROM {table} WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": row_id},
                )
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() AND state = 'idle in transaction'"
                    )
                )
                == 0
            )
        result = api.fixture_result(request)
        evidence = {
            "source": "context",
            "id": "req-1",
            "quote": world["body"]["context_items"][0]["text"],
        }
        result.update(
            review_status="needs_clarification",
            change_groups=[],
            questions=[
                {
                    "id": "q-synthetic",
                    "prompt": "Clarify the requirement?",
                    "reason": "Synthetic question",
                    "evidence": [evidence],
                }
            ],
            change_outcomes=[
                {
                    "context_item_id": "req-1",
                    "status": "needs_clarification",
                    "rationale": "Synthetic clarification",
                    "change_group_ids": [],
                    "question_ids": ["q-synthetic"],
                    "evidence": [evidence],
                }
            ],
        )
        # Mutation after making the response must not rewrite the worker's stored request.
        object.__setattr__(request.context.items[0], "text", PRIVATE)
        return result

    outcome = api.run_once(engine, adapter=adapter)
    assert outcome.outcome == "succeeded" and outcome.run_id == run_id
    assert calls == [original]
    row = run_row(engine, run_id)
    assert row["request_payload"] == original and row["status"] == "succeeded"
    assert row["result_payload"]["review_status"] == "needs_clarification"
    assert row["attempt_count"] == 1 and row["error_code"] is None
    history = attempts(engine, run_id)
    assert history[0]["status"] == "succeeded"
    assert history[0]["metadata"] == {
        "adapter": "fixture",
        "adapter_version": "1",
        "model": None,
        "prompt_version": None,
        "model_calls": 0,
        "duration_ms": history[0]["metadata"]["duration_ms"],
    }
    assert history[0]["metadata"]["duration_ms"] >= 0
    with world["client"]() as client:
        response = client.get(f"/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["result"]["review_status"] == "needs_clarification"
    assert api.claim_next(engine) is None


def test_invalid_result_is_terminal_and_does_not_persist_the_raw_payload(run_world):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    original = deepcopy(run_row(engine, run_id)["request_payload"])

    def adapter(request):
        object.__setattr__(request.context.items[0], "text", PRIVATE)
        # Structurally valid, but its evidence quotes the adapter's mutation, not saved input.
        return api.fixture_result(request)

    outcome = api.run_once(engine, adapter=adapter)
    assert outcome.outcome == "failed" and outcome.run_id == run_id
    row = assert_failed(engine, run_id, "invalid_result")
    assert row["request_payload"] == original and row["attempt_count"] == 1
    history = attempts(engine, run_id)
    assert history[0]["status"] == "failed" and history[0]["error_code"] == "invalid_result"
    assert PRIVATE not in repr(history)
    assert api.claim_next(engine) is None


@pytest.mark.parametrize(
    "error_type,code", [(RuntimeError, "adapter_error"), (TimeoutError, "adapter_timeout")]
)
def test_run_once_calls_adapter_once_and_defers_bounded_retry(run_world, error_type, code):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    calls = []

    def adapter(request):
        calls.append(request.run_id)
        raise error_type(PRIVATE)

    settings = api.WorkerSettings(max_attempts=2, retry_delay_seconds=0)
    first = api.run_once(engine, adapter=adapter, settings=settings)
    assert first.outcome == "retry_scheduled" and first.run_id == run_id
    assert calls == [str(run_id)]
    assert run_row(engine, run_id)["status"] == "queued"
    second = api.run_once(engine, adapter=adapter, settings=settings)
    assert second.outcome == "failed" and second.run_id == run_id
    assert calls == [str(run_id)] * 2
    row = assert_failed(engine, run_id, "attempts_exhausted")
    assert row["attempt_count"] == 2
    history = attempts(engine, run_id)
    assert len(history) == 2 and history[0]["id"] != history[1]["id"]
    assert all(item["status"] == "failed" and item["error_code"] == code for item in history)
    assert PRIVATE not in repr(history)


@pytest.mark.parametrize("raises_error", [False, True])
def test_run_once_reports_stale_without_harming_a_reclaimed_attempt(run_world, raises_error):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    replacement = []

    def adapter(request):
        expire_lease(engine, run_id)
        replacement.append(api.claim_next(engine))
        if raises_error:
            raise RuntimeError(PRIVATE)
        return api.fixture_result(request)

    outcome = api.run_once(engine, adapter=adapter)
    assert outcome.outcome == "stale" and outcome.run_id == run_id
    row = run_row(engine, run_id)
    assert row["status"] == "running" and row["attempt_count"] == 2
    assert row["active_attempt_id"] == replacement[0].attempt_id
    assert row["error_code"] is None and row["result_payload"] is None


@pytest.mark.parametrize("interruption", [SystemExit, KeyboardInterrupt])
def test_process_interruptions_propagate_and_leave_recoverable_lease(run_world, interruption):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)

    def adapter(request):
        raise interruption()

    with pytest.raises(interruption):
        api.run_once(engine, adapter=adapter)
    row = run_row(engine, run_id)
    assert row["status"] == "running" and row["attempt_count"] == 1
    assert attempts(engine, run_id)[0]["status"] == "running"


@pytest.mark.parametrize("failure", ["statement", "commit"])
def test_claim_database_failure_rolls_back_and_never_calls_adapter(run_world, failure):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    before = state(engine, run_id)

    def fail(*args, **kwargs):
        raise OperationalError(PRIVATE, {"private": PRIVATE}, Exception(PRIVATE))

    def forbidden(request):
        pytest.fail("Adapter ran before a successful claim commit")

    name = "before_cursor_execute" if failure == "statement" else "commit"
    event.listen(engine, name, fail)
    try:
        safe_storage_failure(lambda: api.run_once(engine, adapter=forbidden))
    finally:
        event.remove(engine, name, fail)
    assert state(engine, run_id) == before


@pytest.mark.parametrize("operation", ["complete", "fail"])
def test_attempt_commit_failure_rolls_back_result_and_history(run_world, operation):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    claim = api.claim_next(engine)
    payload = api.fixture_result(claim.request)
    before = state(engine, run_id)

    def fail(connection):
        raise OperationalError(PRIVATE, {}, Exception(PRIVATE))

    event.listen(engine, "commit", fail)
    try:
        if operation == "complete":
            safe_storage_failure(lambda: api.complete_attempt(engine, claim, payload))
        else:
            safe_storage_failure(lambda: api.fail_attempt(engine, claim, code="adapter_error"))
    finally:
        event.remove(engine, "commit", fail)
    assert state(engine, run_id) == before


@pytest.mark.parametrize("target", ["result", "attempt"])
def test_write_failure_cannot_leave_a_partial_success(run_world, target):
    api = worker()
    engine = run_world["engine"]
    run_id = enqueue(run_world)
    claim = api.claim_next(engine)
    before = state(engine, run_id)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION ara_reject_worker_finish() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN RAISE EXCEPTION '{PRIVATE}'; END $$"
            )
        )
        clause = (
            "BEFORE UPDATE OF result_payload ON analysis_runs"
            if target == "result"
            else "BEFORE UPDATE OF status ON analysis_attempts"
        )
        connection.execute(
            text(
                f"CREATE TRIGGER ara_reject_finish {clause} FOR EACH ROW "
                "EXECUTE FUNCTION ara_reject_worker_finish()"
            )
        )
    safe_storage_failure(
        lambda: api.complete_attempt(engine, claim, api.fixture_result(claim.request)),
        500,
        "storage_error",
        False,
    )
    assert state(engine, run_id) == before
