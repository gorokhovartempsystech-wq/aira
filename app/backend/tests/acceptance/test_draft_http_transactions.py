"""Independent HTTP concurrency and safe storage failures for local drafts."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from importlib import import_module
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

PRIVATE = "SYNTHETIC_PRIVATE_HTTP_DRAFT_682"
CLIENT_REQUEST_ID = "00000000-0000-4000-8000-000000000682"
FAKE_SQL = "SELECT synthetic_private_column FROM synthetic_private_table"
FAKE_DSN = "postgresql+psycopg://synthetic.invalid/private_database"
SOURCE_TABLES = (
    "users",
    "projects",
    "documents",
    "document_versions",
    "context_revisions",
    "analysis_runs",
    "analysis_attempts",
    "review_revisions",
)


def path(world):
    return f"/documents/{world['documents']['own']['id']}/draft"


def body(world, revision=1, content=PRIVATE):
    return {
        "expected_revision": revision,
        "base_version_id": world["documents"]["own"]["current_version_id"],
        "content_markdown": content,
    }


def seed_draft(world, name="own"):
    document = world["documents"][name]
    return import_module("ara.drafts").save_draft(
        world["runtimes"]["own"],
        document_id=UUID(document["id"]),
        expected_revision=0,
        base_version_id=UUID(document["current_version_id"]),
        content_markdown=PRIVATE + " preserved " + name,
    )


def seed_sources(world):
    """Include existing user decisions as well as the fixture's analysis history."""
    route = f"/runs/{world['runs']['own']['run_id']}/review"
    with world["client"]() as client:
        response = client.get(route)
        assert response.status_code == 200
        review = response.json()
        response = client.put(
            route,
            json={
                "expected_revision_id": review["revision_id"],
                "expected_result_fingerprint": review["result_fingerprint"],
                "decisions": review["decisions"],
            },
        )
        assert response.status_code == 200
    seed_draft(world)
    seed_draft(world, "second")


def records(engine):
    with engine.connect() as connection:
        result = {
            table: [
                dict(row)
                for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
            ]
            for table in SOURCE_TABLES
        }
        # The text cast also permits exact comparison of a corrupted infinity timestamp.
        result["document_drafts"] = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT document_id, base_version_id, revision, content_markdown, "
                    "updated_at::text AS updated_at FROM document_drafts ORDER BY document_id"
                )
            ).mappings()
        ]
        return result


def request(client, world, method, payload=None):
    headers = {"X-Request-ID": CLIENT_REQUEST_ID}
    if method == "GET":
        return client.get(path(world), headers=headers)
    return client.put(
        path(world), json=body(world) if payload is None else payload, headers=headers
    )


def safe_error(response, status, code, retryable=False, *, forbidden=()):
    assert response.status_code == status, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    assert response.headers["content-type"].startswith("application/json")
    value = response.json()
    assert set(value) == {"code", "message", "retryable", "request_id"}
    assert value["code"] == code and value["retryable"] is retryable
    assert isinstance(value["message"], str) and value["message"]
    assert str(UUID(value["request_id"])) == value["request_id"]
    assert value["request_id"] != CLIENT_REQUEST_ID
    for secret in (PRIVATE, FAKE_SQL, FAKE_DSN, "Traceback", *forbidden):
        assert secret not in response.text
    return value["request_id"]


def raise_storage_error(operational, foreign_id):
    if operational:
        raise OperationalError(
            FAKE_SQL, {"input": PRIVATE, "foreign_id": foreign_id}, Exception(FAKE_DSN)
        )
    raise RuntimeError(f"{PRIVATE} {FAKE_SQL} {FAKE_DSN} {foreign_id}")


@contextmanager
def bounded_connections(engine):
    def bound(connection, record):
        previous = connection.autocommit
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
        finally:
            connection.autocommit = previous

    event.listen(engine, "connect", bound)
    try:
        yield
    finally:
        event.remove(engine, "connect", bound)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("same_text", [False, True])
def test_concurrent_http_saves_return_one_winner_and_one_conflict(run_world, existing, same_text):
    world = run_world
    engine = world["engine"]
    revision = seed_draft(world).revision if existing else 0
    before = records(engine)
    texts = ["  First concurrent text\r\n", "  First concurrent text\r\n" if same_text else "Other"]
    barrier = Barrier(2)

    def save(content):
        with world["client"]() as client:
            barrier.wait(timeout=5)
            return request(client, world, "PUT", body(world, revision, content))

    with bounded_connections(engine), ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, content) for content in texts]
        responses = [future.result(timeout=20) for future in futures]
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response for response in responses if response.status_code == 200)
    safe_error(
        next(response for response in responses if response.status_code == 409),
        409,
        "draft_conflict",
        forbidden=tuple(texts),
    )
    assert winner.headers["X-ARA-Auth-Mode"] == "local-dev"
    snapshot = winner.json()
    assert snapshot["revision"] == revision + 1
    assert snapshot["content_markdown"] in texts
    assert snapshot["document_id"] == world["documents"]["own"]["id"]
    assert snapshot["base_version_id"] == world["documents"]["own"]["current_version_id"]
    with world["client"]() as client:
        fetched = request(client, world, "GET")
    assert fetched.status_code == 200 and fetched.json() == snapshot
    after = records(engine)
    assert len(after["document_drafts"]) == 1
    assert after["document_drafts"][0]["revision"] == snapshot["revision"]
    assert after["document_drafts"][0]["content_markdown"] == snapshot["content_markdown"]
    assert {name: after[name] for name in SOURCE_TABLES} == {
        name: before[name] for name in SOURCE_TABLES
    }


@pytest.mark.parametrize("operational", [False, True])
def test_get_and_put_return_safe_storage_errors_and_preserve_records(review_world, operational):
    world = review_world
    engine = world["engine"]
    seed_sources(world)
    before = records(engine)
    assert all(before[name] for name in SOURCE_TABLES)
    foreign_id = world["documents"]["foreign"]["id"]

    def fail_statement(*args):
        raise_storage_error(operational, foreign_id)

    event.listen(engine, "before_cursor_execute", fail_statement)
    try:
        with world["client"]() as client:
            responses = [request(client, world, method) for method in ("GET", "PUT")]
        request_ids = [
            safe_error(
                response,
                503 if operational else 500,
                "storage_unavailable" if operational else "storage_error",
                operational,
                forbidden=(foreign_id,),
            )
            for response in responses
        ]
        assert len(set(request_ids)) == 2
        assert responses[0].json()["message"] == responses[1].json()["message"]
    finally:
        event.remove(engine, "before_cursor_execute", fail_statement)
    assert records(engine) == before


@pytest.mark.parametrize("method", ["GET", "PUT"])
@pytest.mark.parametrize("operational", [False, True])
def test_commit_failure_never_returns_success_or_leaves_partial_http_save(
    review_world, method, operational
):
    world = review_world
    engine = world["engine"]
    seed_sources(world)
    before = records(engine)
    foreign_id = world["documents"]["foreign"]["id"]

    def fail_commit(connection):
        raise_storage_error(operational, foreign_id)

    event.listen(engine, "commit", fail_commit)
    try:
        with world["client"]() as client:
            response = request(client, world, method)
        safe_error(
            response,
            503 if operational else 500,
            "storage_unavailable" if operational else "storage_error",
            operational,
            forbidden=(foreign_id,),
        )
    finally:
        event.remove(engine, "commit", fail_commit)
    assert records(engine) == before
    with world["client"]() as client:
        fetched = request(client, world, "GET")
    assert fetched.status_code == 200
    assert fetched.json()["revision"] == 1
    assert fetched.json()["content_markdown"] == PRIVATE + " preserved own"


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_infinite_draft_timestamp_returns_safe_http_500_without_overwrite(run_world, method):
    world = run_world
    engine = world["engine"]
    seed_draft(world)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE document_drafts SET updated_at='infinity' WHERE document_id=:id"),
            {"id": UUID(world["documents"]["own"]["id"])},
        )
    before = records(engine)
    assert before["document_drafts"][0]["updated_at"] == "infinity"
    with world["client"]() as client:
        response = request(client, world, method)
    safe_error(response, 500, "storage_error")
    assert records(engine) == before
