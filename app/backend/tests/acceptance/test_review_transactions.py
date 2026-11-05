"""Independent PostgreSQL races, replay and transaction safety for review revisions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Barrier, Event
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

PRIVATE = "SYNTHETIC_PRIVATE_REVIEW_917"
SOURCE_TABLES = (
    "users",
    "projects",
    "documents",
    "document_versions",
    "context_revisions",
    "analysis_runs",
    "analysis_attempts",
)


def path(world, name="own"):
    return f"/runs/{world['runs'][name]['run_id']}/review"


def saved(engine, tables=SOURCE_TABLES):
    with engine.connect() as connection:
        return {
            table: [
                dict(row)
                for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
            ]
            for table in tables
        }


def reviews(engine):
    return saved(engine, ("review_revisions",))["review_revisions"]


def current(world, name="own"):
    with world["client"]() as client:
        response = client.get(path(world, name))
    assert response.status_code == 200, response.text
    return response.json()


def body_for(response):
    return {
        "expected_revision_id": response["revision_id"],
        "expected_result_fingerprint": response["result_fingerprint"],
        "decisions": deepcopy(response["decisions"]),
    }


def put(world, body, name="own"):
    with world["client"]() as client:
        return client.put(path(world, name), json=body, headers={"X-Request-ID": PRIVATE})


def write(world, body, name="own"):
    response = put(world, body, name)
    assert response.status_code == 200, response.text
    return response.json()


def edit_first(world, body, value, name="own"):
    for group in world["runs"][name]["result"]["change_groups"]:
        for patch_index, patch in enumerate(group["patches"]):
            if patch["new_blocks"]:
                decision = next(
                    item for item in body["decisions"] if item["group_id"] == group["id"]
                )
                decision["decision"] = "accepted"
                decision["edits"] = [
                    {"patch_index": patch_index, "new_block_index": 0, "text": value}
                ]
                return
    raise AssertionError("The synthetic review must have one editable proposal")


def error(response, status, code, retryable=False):
    assert response.status_code == status, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    value = response.json()
    assert set(value) == {"code", "message", "retryable", "request_id"}
    assert value["code"] == code and value["retryable"] is retryable
    assert isinstance(value["message"], str) and value["message"]
    assert isinstance(value["request_id"], str) and value["request_id"]
    assert PRIVATE not in response.text


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


@pytest.mark.parametrize("existing_parent", [False, True])
@pytest.mark.parametrize("same_body", [False, True])
def test_concurrent_puts_create_exactly_one_child(review_world, existing_parent, same_body):
    world = review_world
    engine = world["engine"]
    parent = current(world)
    if existing_parent:
        parent = write(world, body_for(parent))
    previous = reviews(engine)
    source = saved(engine)
    bodies = [body_for(parent), body_for(parent)]
    edit_first(world, bodies[0], "  Saved proposal\r\n")
    edit_first(world, bodies[1], "  Saved proposal\r\n" if same_body else "Different proposal")
    if same_body:
        bodies[1]["decisions"].reverse()
    barrier = Barrier(2)

    def save(body):
        with world["client"]() as client:
            barrier.wait(timeout=5)
            return client.put(path(world), json=body)

    with bounded_connections(engine), ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, body) for body in bodies]
        responses = [future.result(timeout=20) for future in futures]
    assert sorted(response.status_code for response in responses) == (
        [200, 200] if same_body else [200, 409]
    )
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert winner["parent_revision_id"] == parent["revision_id"]
    assert winner["revision_number"] == parent["revision_number"] + 1
    assert any(
        {item["group_id"]: item for item in winner["decisions"]}
        == {item["group_id"]: item for item in body["decisions"]}
        for body in bodies
    )
    if same_body:
        assert responses[0].json() == responses[1].json()
    else:
        error(
            next(response for response in responses if response.status_code == 409),
            409,
            "review_conflict",
        )
    assert current(world) == winner
    after = reviews(engine)
    assert len(after) == len(previous) + 1
    assert all(row in after for row in previous)
    assert saved(engine) == source


def test_replay_of_old_parent_returns_its_child_after_descendants_exist(review_world):
    world = review_world
    source = saved(world["engine"])
    first_body = body_for(current(world))
    edit_first(world, first_body, "  Original user edit\r\n\t")
    group = next(item for item in first_body["decisions"] if item["group_id"] == "g1")
    group["edits"].append(
        {"patch_index": 0, "new_block_index": 1, "text": "```text\r\nSecond block\r\n```"}
    )
    first = write(world, first_body)
    second_body = body_for(first)
    edit_first(world, second_body, "Second user edit")
    second = write(world, second_body)
    # A new expected parent is an explicit new save, even with identical decisions.
    third_body = body_for(second)
    third = write(world, third_body)
    assert third["revision_number"] == 3
    assert third["parent_revision_id"] == second["revision_id"]
    assert third["decisions"] == second["decisions"]
    before = reviews(world["engine"])
    for original, expected in ((first_body, first), (second_body, second)):
        reordered = deepcopy(original)
        reordered["decisions"].reverse()
        for decision in reordered["decisions"]:
            decision["edits"].reverse()
        reordered = dict(reversed(list(reordered.items())))
        assert write(world, reordered) == expected
        different = deepcopy(original)
        edit_first(world, different, "An edit that must not overwrite history")
        error(put(world, different), 409, "review_conflict")
    with world["client"]() as client:
        for revision in (first, second, third):
            response = client.get(path(world), params={"revision_id": revision["revision_id"]})
            assert response.status_code == 200
            assert response.json() == revision
    assert current(world) == third
    assert reviews(world["engine"]) == before
    assert saved(world["engine"]) == source


@pytest.mark.parametrize("failure", ["insert", "unrelated_unique", "commit", "other_commit"])
def test_failed_write_preserves_existing_revisions_and_every_source_record(review_world, failure):
    world = review_world
    engine = world["engine"]
    first = write(world, body_for(current(world)))
    body = body_for(first)
    edit_first(world, body, "Existing edit")
    second = write(world, body)
    write(world, body_for(current(world, "second")), "second")
    before = saved(engine, (*SOURCE_TABLES, "review_revisions"))
    failing_body = body_for(second)
    edit_first(world, failing_body, PRIVATE)

    if failure in ("insert", "unrelated_unique"):
        exception = f"RAISE EXCEPTION '{PRIVATE}'"
        if failure == "unrelated_unique":
            exception += " USING ERRCODE = '23505', CONSTRAINT = 'synthetic_other_constraint'"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION ara_fail_review() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    f"BEGIN {exception}; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER ara_review_failure BEFORE INSERT ON review_revisions "
                    "FOR EACH ROW EXECUTE FUNCTION ara_fail_review()"
                )
            )

    def fail_commit(connection):
        if failure == "commit":
            raise OperationalError(PRIVATE, {"secret": PRIVATE}, Exception(PRIVATE))
        raise RuntimeError(PRIVATE)

    if failure in ("commit", "other_commit"):
        event.listen(engine, "commit", fail_commit)
    try:
        response = put(world, failing_body)
        error(
            response,
            503 if failure == "commit" else 500,
            "storage_unavailable" if failure == "commit" else "storage_error",
            failure == "commit",
        )
    finally:
        if failure in ("commit", "other_commit"):
            event.remove(engine, "commit", fail_commit)
    assert saved(engine, (*SOURCE_TABLES, "review_revisions")) == before
    assert current(world) == second
    with world["client"]() as client:
        response = client.get(path(world), params={"revision_id": first["revision_id"]})
        assert response.status_code == 200 and response.json() == first


@pytest.mark.parametrize("operational", [False, True])
def test_get_and_put_storage_errors_hide_exception_and_do_not_change_data(
    review_world, operational
):
    world = review_world
    engine = world["engine"]
    first = write(world, body_for(current(world)))
    body = body_for(first)
    edit_first(world, body, PRIVATE)
    before = saved(engine, (*SOURCE_TABLES, "review_revisions"))

    def fail_statement(*args):
        if operational:
            raise OperationalError(PRIVATE, {"secret": PRIVATE}, Exception(PRIVATE))
        raise RuntimeError(PRIVATE)

    event.listen(engine, "before_cursor_execute", fail_statement)
    try:
        with world["client"]() as client:
            responses = [client.get(path(world)), client.put(path(world), json=body)]
        for response in responses:
            error(
                response,
                503 if operational else 500,
                "storage_unavailable" if operational else "storage_error",
                operational,
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_statement)
    assert saved(engine, (*SOURCE_TABLES, "review_revisions")) == before


@pytest.mark.parametrize("change", ["owner", "project"])
def test_scope_is_locked_until_revision_insert_commits(review_world, change):
    world = review_world
    engine = world["engine"]
    body = body_for(current(world))
    edit_first(world, body, "Save under the verified owner and project")
    source = saved(engine)
    inserting, release = Event(), Event()

    def pause_insert(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().lower()
        if normalized.startswith("insert") and "review_revisions" in normalized:
            inserting.set()
            assert release.wait(timeout=10), "The test must release the paused insert"

    event.listen(engine, "before_cursor_execute", pause_insert)
    try:
        with bounded_connections(engine), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(put, world, body)
            try:
                assert inserting.wait(timeout=5), "Review must reach its insert"
                with pytest.raises(OperationalError) as caught:
                    with engine.begin() as connection:
                        connection.execute(text("SET LOCAL lock_timeout = '250ms'"))
                        if change == "owner":
                            connection.execute(
                                text("UPDATE projects SET owner_id = :owner WHERE id = :id"),
                                {
                                    "owner": world["owners"]["foreign"],
                                    "id": world["projects"]["own"],
                                },
                            )
                        else:
                            connection.execute(
                                text("UPDATE documents SET project_id = :project WHERE id = :id"),
                                {
                                    "project": world["projects"]["peer"],
                                    "id": UUID(world["documents"]["own"]["id"]),
                                },
                            )
                assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
            finally:
                release.set()
            response = future.result(timeout=10)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", pause_insert)
    assert response.status_code == 200, response.text
    assert response.json()["revision_number"] == 1
    assert current(world) == response.json()
    assert len(reviews(engine)) == 1
    assert saved(engine) == source
