"""Independent real-database concurrency and failure acceptance for enqueueing."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

PRIVATE = "SYNTHETIC_PRIVATE_RUN_735"
KEY = "private-idempotency-key-735"


def _post(world, client, body=None):
    document_id = world["documents"]["own"]["id"]
    return client.post(
        f"/documents/{document_id}/runs",
        json=world["body"] if body is None else body,
        headers={"Idempotency-Key": KEY, "X-Request-ID": "client-controlled"},
    )


def _error(response, status, code, retryable=False):
    assert response.status_code == status, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    body = response.json()
    assert set(body) == {"code", "message", "retryable", "request_id"}
    assert body["code"] == code and body["retryable"] is retryable
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["request_id"], str) and body["request_id"]
    assert body["request_id"] != "client-controlled"
    assert PRIVATE not in response.text and KEY not in response.text


def _counts(engine):
    with engine.connect() as connection:
        return tuple(
            connection.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("context_revisions", "analysis_runs")
        )


def _saved_records(engine):
    with engine.connect() as connection:
        return {
            table: [
                dict(row)
                for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
            ]
            for table in ("context_revisions", "analysis_runs")
        }


@pytest.mark.parametrize("same_body", [True, False])
def test_concurrent_posts_create_one_run_and_context(run_world, same_body):
    world = run_world
    barrier = Barrier(2)

    def bound_connection(connection, record):
        previous = connection.autocommit
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
        finally:
            connection.autocommit = previous

    def create(body):
        with world["client"]() as client:
            barrier.wait(timeout=5)
            return _post(world, client, body)

    bodies = [deepcopy(world["body"]), deepcopy(world["body"])]
    if not same_body:
        bodies[1]["context_items"][0]["text"] = "A different requested change"
    event.listen(world["engine"], "connect", bound_connection)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create, body) for body in bodies]
            responses = [future.result(timeout=25) for future in futures]
    finally:
        event.remove(world["engine"], "connect", bound_connection)
    assert sorted(response.status_code for response in responses) == (
        [202, 202] if same_body else [202, 409]
    )
    if same_body:
        assert responses[0].json() == responses[1].json()
    else:
        _error(
            next(response for response in responses if response.status_code == 409),
            409,
            "idempotency_conflict",
        )
    assert _counts(world["engine"]) == (1, 1)
    winner = next(response.json() for response in responses if response.status_code == 202)
    with world["client"]() as client:
        assert client.get(f"/runs/{winner['run_id']}").json() == winner
        winning_body = next(
            body
            for body in bodies
            if body["context_items"] == winner["request"]["context"]["items"]
        )
        assert _post(world, client, winning_body).json() == winner
    assert _counts(world["engine"]) == (1, 1)


@pytest.mark.parametrize("failure", ["context", "run", "unrelated-unique", "commit"])
def test_enqueue_failure_rolls_back_all_new_records(run_world, failure):
    world = run_world
    engine = world["engine"]
    with world["client"]() as client:
        existing = client.post(
            f"/documents/{world['documents']['own']['id']}/runs",
            json=world["body"],
            headers={"Idempotency-Key": "previous-successful-request"},
        )
        assert existing.status_code == 202
    before = _saved_records(engine)
    if failure != "commit":
        table = "context_revisions" if failure == "context" else "analysis_runs"
        exception = f"RAISE EXCEPTION '{PRIVATE}'"
        if failure == "unrelated-unique":
            exception += " USING ERRCODE = '23505', CONSTRAINT = 'synthetic_other_constraint'"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION ara_fail_enqueue() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    f"BEGIN {exception}; END $$"
                )
            )
            connection.execute(
                text(
                    f"CREATE TRIGGER ara_enqueue_failure BEFORE INSERT ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION ara_fail_enqueue()"
                )
            )

    def fail_commit(connection):
        raise OperationalError(PRIVATE, {}, Exception(PRIVATE))

    if failure == "commit":
        event.listen(engine, "commit", fail_commit)
    try:
        body = deepcopy(world["body"])
        body["context_items"][0]["text"] = PRIVATE
        with world["client"]() as client:
            response = _post(world, client, body)
        _error(
            response,
            503 if failure == "commit" else 500,
            "storage_unavailable" if failure == "commit" else "storage_error",
            failure == "commit",
        )
    finally:
        if failure == "commit":
            event.remove(engine, "commit", fail_commit)
    assert _saved_records(engine) == before
    assert _counts(engine) == (1, 1)


def test_storage_unavailable_is_safe_for_create_and_get(run_world):
    world = run_world
    with world["client"]() as client:
        created = _post(world, client)
        assert created.status_code == 202
        run_id = created.json()["run_id"]

        def unavailable(*args, **kwargs):
            raise OperationalError(PRIVATE, {"private": PRIVATE}, Exception(PRIVATE))

        event.listen(world["engine"], "before_cursor_execute", unavailable)
        try:
            _error(_post(world, client), 503, "storage_unavailable", True)
            _error(client.get(f"/runs/{run_id}"), 503, "storage_unavailable", True)
        finally:
            event.remove(world["engine"], "before_cursor_execute", unavailable)
    assert _counts(world["engine"]) == (1, 1)


def test_invalid_stored_source_never_becomes_a_queued_run(run_world):
    world = run_world
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE document_versions SET blocks = CAST(:blocks AS jsonb) WHERE id = :id"),
            {
                "id": UUID(world["body"]["base_version_id"]),
                "blocks": '[{"id":"bad","kind":"invalid","text":"Synthetic"}]',
            },
        )
    with world["client"]() as client:
        _error(_post(world, client), 500, "storage_error")
    assert _counts(world["engine"]) == (0, 0)
