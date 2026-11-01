"""Independent PostgreSQL concurrency, access and rollback checks for local drafts."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from importlib import import_module
from threading import Barrier, Event, get_ident
from time import monotonic, sleep
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

PRIVATE = "SYNTHETIC_PRIVATE_DRAFT_481"
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


def api():
    return import_module("ara.drafts")


def error_type():
    return import_module("ara.documents.storage").DocumentError


def ids(world, name="own"):
    document = world["documents"][name]
    return UUID(document["id"]), UUID(document["current_version_id"])


def save(world, revision, content, name="own"):
    document, base = ids(world, name)
    return api().save_draft(
        world["runtimes"]["own"],
        document_id=document,
        expected_revision=revision,
        base_version_id=base,
        content_markdown=content,
    )


def read(world):
    return api().read_draft(world["runtimes"]["own"], document_id=ids(world)[0])


def records(engine, tables=SOURCE_TABLES):
    with engine.connect() as connection:
        result = {}
        for table in tables:
            key = "document_id" if table == "document_drafts" else "id"
            result[table] = [
                dict(row)
                for row in connection.execute(
                    text(f"SELECT * FROM {table} ORDER BY {key}")
                ).mappings()
            ]
        return result


def assert_error(error, status, code, retryable=False):
    assert isinstance(error, error_type())
    assert (error.status, error.code, error.retryable) == (status, code, retryable)
    assert isinstance(error.message, str) and error.message
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
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
        finally:
            connection.autocommit = previous

    event.listen(engine, "connect", bound)
    try:
        yield
    finally:
        event.remove(engine, "connect", bound)


@contextmanager
def observe_backend(engine):
    """Identify the worker connection without assuming its SQL implementation."""
    caller = get_ident()
    started = Event()
    backend = {}

    def observe(connection, cursor, statement, parameters, context, executemany):
        if get_ident() != caller:
            backend["pid"] = connection.connection.driver_connection.info.backend_pid
            started.set()

    event.listen(engine, "before_cursor_execute", observe)
    try:
        yield started, backend
    finally:
        event.remove(engine, "before_cursor_execute", observe)


def wait_for_lock(engine, started, backend):
    assert started.wait(timeout=3), "The draft operation must start SQL"
    deadline = monotonic() + 3
    with engine.connect() as observer:
        while monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            waiting = observer.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"), backend
            )
            if waiting == "Lock":
                return
            sleep(0.01)
    raise AssertionError("The draft operation must wait for the held scope lock")


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("same_text", [False, True])
def test_concurrent_first_and_later_saves_have_one_winner(run_world, existing, same_text):
    world = run_world
    api()
    expected = save(world, 0, "Previous draft").revision if existing else 0
    source = records(world["engine"])
    barrier = Barrier(2)
    texts = ["  Concurrent draft\r\n", "  Concurrent draft\r\n" if same_text else "Other draft"]

    def saving(content):
        barrier.wait(timeout=5)
        try:
            return save(world, expected, content)
        except error_type() as error:
            return error

    with bounded_connections(world["engine"]), ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(saving, content) for content in texts]
        results = [future.result(timeout=20) for future in futures]
    errors = [result for result in results if isinstance(result, error_type())]
    winners = [result for result in results if not isinstance(result, error_type())]
    assert len(errors) == len(winners) == 1
    assert_error(errors[0], 409, "draft_conflict")
    winner = winners[0]
    assert winner.revision == expected + 1 and winner.content_markdown in texts
    assert read(world).model_dump() == winner.model_dump()
    assert len(records(world["engine"], ("document_drafts",))["document_drafts"]) == 1
    # Even a precise repeat is a conflict, not review-style idempotent replay.
    with pytest.raises(error_type()) as caught:
        save(world, expected, winner.content_markdown)
    assert_error(caught.value, 409, "draft_conflict")
    assert read(world).model_dump() == winner.model_dump()
    assert records(world["engine"]) == source


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["write", "commit", "other_commit"])
def test_failed_insert_update_or_commit_preserves_old_draft_and_sources(
    review_world, existing, failure
):
    world = review_world
    engine = world["engine"]
    api()
    # Keep all eight old tables nonempty, including an immutable review revision.
    with world["client"]() as client:
        route = f"/runs/{world['runs']['own']['run_id']}/review"
        review = client.get(route)
        assert review.status_code == 200
        review = review.json()
        response = client.put(
            route,
            json={
                "expected_revision_id": review["revision_id"],
                "expected_result_fingerprint": review["result_fingerprint"],
                "decisions": review["decisions"],
            },
        )
        assert response.status_code == 200
    save(world, 0, "An unrelated document's existing draft", "second")
    expected = save(world, 0, "Original draft\r\n").revision if existing else 0
    before = records(engine, (*SOURCE_TABLES, "document_drafts"))
    assert all(before[name] for name in SOURCE_TABLES)
    if failure == "write":
        operation = "UPDATE" if existing else "INSERT"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION ara_fail_draft_write() RETURNS trigger LANGUAGE plpgsql AS $$ "
                    f"BEGIN RAISE EXCEPTION '{PRIVATE}'; END $$"
                )
            )
            connection.execute(
                text(
                    f"CREATE TRIGGER ara_draft_failure AFTER {operation} ON document_drafts "
                    "FOR EACH ROW EXECUTE FUNCTION ara_fail_draft_write()"
                )
            )

    def fail_commit(connection):
        if failure == "commit":
            raise OperationalError(PRIVATE, {"private": PRIVATE}, Exception(PRIVATE))
        raise RuntimeError(PRIVATE)

    if failure != "write":
        event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(error_type()) as caught:
            save(world, expected, PRIVATE)
        assert_error(
            caught.value,
            503 if failure == "commit" else 500,
            "storage_unavailable" if failure == "commit" else "storage_error",
            failure == "commit",
        )
    finally:
        if failure != "write":
            event.remove(engine, "commit", fail_commit)
    assert records(engine, (*SOURCE_TABLES, "document_drafts")) == before


@pytest.mark.parametrize("operation", ["read", "save"])
@pytest.mark.parametrize("operational", [False, True])
def test_storage_failures_are_safe_and_preserve_every_record(run_world, operation, operational):
    world = run_world
    engine = world["engine"]
    save(world, 0, "Original draft")
    before = records(engine, (*SOURCE_TABLES, "document_drafts"))

    def fail_statement(*args):
        if operational:
            raise OperationalError(PRIVATE, {"private": PRIVATE}, Exception(PRIVATE))
        raise RuntimeError(PRIVATE)

    event.listen(engine, "before_cursor_execute", fail_statement)
    try:
        with pytest.raises(error_type()) as caught:
            read(world) if operation == "read" else save(world, 1, PRIVATE)
        assert_error(
            caught.value,
            503 if operational else 500,
            "storage_unavailable" if operational else "storage_error",
            operational,
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail_statement)
    assert records(engine, (*SOURCE_TABLES, "document_drafts")) == before


@pytest.mark.parametrize("operation", ["read", "save"])
@pytest.mark.parametrize("change", ["owner", "project"])
def test_read_and_save_keep_scope_locked_until_transaction_end(run_world, operation, change):
    world = run_world
    engine = world["engine"]
    original = save(world, 0, "Original draft")
    source = records(engine)
    reached, release = Event(), Event()
    caller = get_ident()

    def pause(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().lower()
        relevant = (
            normalized.startswith("select")
            if operation == "read"
            else (normalized.startswith(("insert", "update")))
        )
        if get_ident() != caller and relevant and "document_drafts" in normalized:
            reached.set()
            assert release.wait(timeout=10), "The test must release the operation"

    event.listen(engine, "after_cursor_execute", pause)
    try:
        with bounded_connections(engine), ThreadPoolExecutor(max_workers=1) as executor:
            future = (
                executor.submit(read, world)
                if operation == "read"
                else executor.submit(save, world, 1, "New draft")
            )
            try:
                assert reached.wait(timeout=5), "The operation must reach its draft query"
                with pytest.raises(OperationalError) as caught:
                    with engine.begin() as connection:
                        connection.execute(text("SET LOCAL lock_timeout = '250ms'"))
                        if change == "owner":
                            connection.execute(
                                text("UPDATE projects SET owner_id=:owner WHERE id=:id"),
                                {
                                    "owner": world["owners"]["foreign"],
                                    "id": world["projects"]["own"],
                                },
                            )
                        else:
                            connection.execute(
                                text("UPDATE documents SET project_id=:project WHERE id=:id"),
                                {"project": world["projects"]["peer"], "id": ids(world)[0]},
                            )
                assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
            finally:
                release.set()
            result = future.result(timeout=10)
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", pause)
    assert result.revision == (1 if operation == "read" else 2)
    if operation == "read":
        assert result.model_dump() == original.model_dump()
    else:
        assert result.content_markdown == "New draft"
    assert read(world).model_dump() == result.model_dump()
    assert records(engine) == source


@pytest.mark.parametrize("operation", ["read", "save"])
@pytest.mark.parametrize("change", ["owner", "project"])
def test_access_is_rechecked_after_waiting_for_scope_lock(run_world, operation, change):
    world = run_world
    engine = world["engine"]
    original = save(world, 0, "Original draft")
    before = records(engine, ("document_drafts",))
    with bounded_connections(engine), observe_backend(engine) as (started, backend):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with engine.begin() as blocker:
                table = "projects" if change == "owner" else "documents"
                key = world["projects"]["own"] if change == "owner" else ids(world)[0]
                blocker.execute(
                    text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE"), {"id": key}
                )
                future = (
                    executor.submit(read, world)
                    if operation == "read"
                    else executor.submit(save, world, 1, PRIVATE)
                )
                wait_for_lock(engine, started, backend)
                assert not future.done()
                if change == "owner":
                    blocker.execute(
                        text("UPDATE projects SET owner_id=:owner WHERE id=:id"),
                        {"owner": world["owners"]["foreign"], "id": key},
                    )
                else:
                    blocker.execute(
                        text("UPDATE documents SET project_id=:project WHERE id=:id"),
                        {"project": world["projects"]["peer"], "id": key},
                    )
            with pytest.raises(error_type()) as caught:
                future.result(timeout=10)
    assert_error(caught.value, 404, "not_found")
    not_found = import_module("ara.documents.storage")._not_found()
    assert caught.value.message == not_found.message
    assert records(engine, ("document_drafts",)) == before
    runtime = (
        replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
        if (change == "owner")
        else world["runtimes"]["peer"]
    )
    assert (
        api().read_draft(runtime, document_id=ids(world)[0]).model_dump() == original.model_dump()
    )


@pytest.mark.parametrize("existing", [False, True])
def test_save_timestamp_uses_fresh_database_clock_after_lock_wait(run_world, existing):
    world = run_world
    engine = world["engine"]
    expected_revision = save(world, 0, "Original draft").revision if existing else 0
    source = records(engine)
    with bounded_connections(engine), observe_backend(engine) as (started, backend):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with engine.begin() as blocker:
                blocker.execute(
                    text("SELECT id FROM documents WHERE id=:id FOR UPDATE"), {"id": ids(world)[0]}
                )
                future = executor.submit(save, world, expected_revision, "New draft")
                wait_for_lock(engine, started, backend)
                before_release = blocker.scalar(text("SELECT clock_timestamp()"))
            result = future.result(timeout=10)
    with engine.connect() as connection:
        after = connection.scalar(text("SELECT clock_timestamp()"))
    assert before_release <= result.updated_at <= after
    assert result.revision == expected_revision + 1 and result.content_markdown == "New draft"
    assert read(world).model_dump() == result.model_dump()
    assert records(engine) == source


@pytest.mark.parametrize("operation", ["read", "save"])
def test_infinite_updated_at_fails_safely_without_repairing_or_overwriting_row(
    run_world, operation
):
    world = run_world
    engine = world["engine"]
    save(world, 0, PRIVATE)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE document_drafts SET updated_at='infinity' WHERE document_id=:id"),
            {"id": ids(world)[0]},
        )

    def raw_draft():
        # PostgreSQL infinity is valid SQL but cannot become a finite Python datetime.
        with engine.connect() as connection:
            return dict(
                connection.execute(
                    text(
                        "SELECT document_id, base_version_id, revision, content_markdown, "
                        "updated_at::text AS updated_at FROM document_drafts WHERE document_id=:id"
                    ),
                    {"id": ids(world)[0]},
                )
                .mappings()
                .one()
            )

    source, before = records(engine), raw_draft()
    assert before["updated_at"] == "infinity"
    with pytest.raises(error_type()) as caught:
        read(world) if operation == "read" else save(world, 1, "Must not overwrite damaged draft")
    assert_error(caught.value, 500, "storage_error")
    assert raw_draft() == before
    assert records(engine) == source
