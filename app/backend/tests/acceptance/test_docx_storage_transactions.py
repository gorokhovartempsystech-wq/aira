"""Independent DOCX races, scope locks, rollback and uncertain-commit acceptance."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Barrier, Event, get_ident
from time import monotonic, sleep
from uuid import uuid4

import pytest
from docx_storage_fixtures import api, raw
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_docx_storage_boundaries import PRIVATE, records, reject

from ara.documents.storage import DocumentError


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
    caller, started, backend = get_ident(), Event(), {}

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
    assert started.wait(timeout=3), "The storage operation must start SQL"
    deadline = monotonic() + 3
    with engine.connect() as observer:
        while monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            if (
                observer.scalar(
                    text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), backend
                )
                == "Lock"
            ):
                return
            sleep(0.01)
    raise AssertionError("The operation must wait for the held scope lock")


def stored(world):
    document_id, data = uuid4(), raw()
    value = api().import_docx(
        world["runtimes"]["own"], document_id=document_id, title="Original", data=data
    )
    return document_id, value


def command(world, document_id, operation):
    service, runtime = api(), world["runtimes"]["own"]
    if operation == "get":
        return service.get_docx(runtime, document_id=document_id)
    if operation == "replay":
        return service.import_docx(runtime, document_id=document_id, title="Original", data=raw())
    return service.save_docx(
        runtime, document_id=document_id, expected_storage_revision=1, data=raw("changed")
    )


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_imports_share_one_identity_and_never_reset_it(run_world, different):
    service, world = api(), run_world
    runtime, engine = world["runtimes"]["own"], world["engine"]
    document_id, barrier = uuid4(), Barrier(2)
    payloads = (raw("one"), raw("two" if different else "one"))

    def importing(data):
        barrier.wait(timeout=5)
        try:
            return service.import_docx(
                runtime, document_id=document_id, title="Original", data=data
            )
        except DocumentError as error:
            return error

    with bounded_connections(engine), ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(importing, data) for data in payloads]
        results = [future.result(timeout=15) for future in futures]
    failures = [item for item in results if isinstance(item, DocumentError)]
    successes = [item for item in results if not isinstance(item, DocumentError)]
    assert len(failures) == int(different) and len(successes) == 2 - int(different)
    if failures:
        assert (failures[0].status, failures[0].code, failures[0].retryable) == (
            409,
            "import_conflict",
            False,
        )
    winner = service.get_docx(runtime, document_id=document_id)
    assert all(item == winner for item in successes)
    assert winner.storage_revision == 1 and winner.original_data in payloads
    assert winner.current_data == winner.original_data
    assert len(records(engine)) == 1
    changed = service.save_docx(
        runtime, document_id=document_id, expected_storage_revision=1, data=raw("new work")
    )
    assert (
        service.import_docx(
            runtime, document_id=document_id, title="Original", data=winner.original_data
        )
        == changed
    )


@pytest.mark.parametrize("same_bytes", [False, True])
def test_concurrent_saves_have_exactly_one_winner_and_no_hash_replay(run_world, same_bytes):
    service, world = api(), run_world
    runtime, engine = world["runtimes"]["own"], world["engine"]
    document_id, original = stored(world)
    barrier = Barrier(2)
    payloads = (raw("first"), raw("first" if same_bytes else "second"))

    def saving(data):
        barrier.wait(timeout=5)
        try:
            return service.save_docx(
                runtime, document_id=document_id, expected_storage_revision=1, data=data
            )
        except DocumentError as error:
            return error

    with bounded_connections(engine), ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(saving, data) for data in payloads]
        results = [future.result(timeout=15) for future in futures]
    failures = [item for item in results if isinstance(item, DocumentError)]
    successes = [item for item in results if not isinstance(item, DocumentError)]
    assert len(failures) == len(successes) == 1
    assert (failures[0].status, failures[0].code, failures[0].retryable) == (
        409,
        "docx_conflict",
        False,
    )
    winner = successes[0]
    assert winner.storage_revision == 2 and winner.current_data in payloads
    assert winner.original_data == original.original_data
    assert service.get_docx(runtime, document_id=document_id) == winner
    reject(
        lambda: service.save_docx(
            runtime, document_id=document_id, expected_storage_revision=1, data=winner.current_data
        ),
        409,
        "docx_conflict",
    )
    # Returning to the original bytes does not restore its obsolete storage revision.
    returned = service.save_docx(
        runtime, document_id=document_id, expected_storage_revision=2, data=original.current_data
    )
    assert returned.storage_revision == 3 and returned.current_data == original.current_data
    reject(
        lambda: service.save_docx(
            runtime,
            document_id=document_id,
            expected_storage_revision=1,
            data=original.current_data,
        ),
        409,
        "docx_conflict",
    )
    assert service.get_docx(runtime, document_id=document_id) == returned


@pytest.mark.parametrize("operation", ["import", "save"])
@pytest.mark.parametrize("failure", ["dto", "write", "commit"])
def test_write_dto_and_commit_failures_roll_back_whole_operation(
    run_world, monkeypatch, operation, failure
):
    service, world = api(), run_world
    engine, runtime = world["engine"], world["runtimes"]["own"]
    existing_id, original = stored(world)
    document_id = uuid4() if operation == "import" else existing_id
    before = records(engine)

    def fail(*args, **kwargs):
        raise RuntimeError(PRIVATE)

    def fail_commit(connection):
        raise OperationalError(PRIVATE, {"private": PRIVATE}, RuntimeError(PRIVATE))

    if failure == "write":
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE FUNCTION ara_docx_fail_write() RETURNS trigger LANGUAGE plpgsql "
                    f"AS $$ BEGIN RAISE EXCEPTION '{PRIVATE}'; END $$"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER ara_docx_write_failure AFTER INSERT OR UPDATE "
                    "ON docx_documents FOR EACH ROW EXECUTE FUNCTION ara_docx_fail_write()"
                )
            )
    with monkeypatch.context() as patch:
        if failure == "dto":
            patch.setattr(service.StoredDocx, "__init__", fail)
        elif failure == "commit":
            event.listen(engine, "commit", fail_commit)
        try:
            reject(
                (
                    lambda: service.import_docx(
                        runtime, document_id=document_id, title=PRIVATE, data=raw("new import")
                    )
                )
                if operation == "import"
                else lambda: service.save_docx(
                    runtime, document_id=document_id, expected_storage_revision=1, data=raw("new")
                ),
                503 if failure == "commit" else 500,
                "storage_unavailable" if failure == "commit" else "storage_error",
                failure == "commit",
            )
        finally:
            if failure == "commit":
                event.remove(engine, "commit", fail_commit)
    assert records(engine) == before
    assert service.get_docx(runtime, document_id=existing_id) == original


def test_lost_commit_ack_is_reconciled_without_overwrite_or_compensation(run_world, monkeypatch):
    service, world = api(), run_world
    engine, runtime = world["engine"], world["runtimes"]["own"]
    document_id, original = stored(world)
    data = raw("committed without acknowledgement")
    real_commit = engine.dialect.do_commit

    def commit_then_lose_ack(connection):
        real_commit(connection)
        raise OperationalError(PRIVATE, {}, RuntimeError(PRIVATE))

    with monkeypatch.context() as patch:
        patch.setattr(engine.dialect, "do_commit", commit_then_lose_ack)
        reject(
            lambda: service.save_docx(
                runtime, document_id=document_id, expected_storage_revision=1, data=data
            ),
            503,
            "storage_unavailable",
            True,
        )
    committed = service.get_docx(runtime, document_id=document_id)
    assert committed.storage_revision == 2 and committed.current_data == data
    assert committed.original_data == original.original_data
    reject(
        lambda: service.save_docx(
            runtime, document_id=document_id, expected_storage_revision=1, data=data
        ),
        409,
        "docx_conflict",
    )
    assert service.get_docx(runtime, document_id=document_id) == committed


@pytest.mark.parametrize(
    "operation,change", [("get", "owner"), ("replay", "project"), ("save", "project")]
)
def test_scope_remains_locked_until_transaction_completion(run_world, operation, change):
    world, engine = run_world, run_world["engine"]
    document_id, original = stored(world)
    reached, release, caller = Event(), Event(), get_ident()

    def pause(connection):
        # A commit hook is independent of query shape and runs while locks must still be held.
        if get_ident() != caller:
            reached.set()
            assert release.wait(timeout=10), "The test must release the storage operation"

    event.listen(engine, "commit", pause)
    try:
        with bounded_connections(engine), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(command, world, document_id, operation)
            try:
                assert reached.wait(timeout=5)
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
                                text("UPDATE docx_documents SET project_id=:project WHERE id=:id"),
                                {"project": world["projects"]["peer"], "id": document_id},
                            )
                assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
            finally:
                release.set()
            result = future.result(timeout=10)
    finally:
        release.set()
        event.remove(engine, "commit", pause)
    assert result.storage_revision == (2 if operation == "save" else 1)
    if operation != "save":
        assert result == original


@pytest.mark.parametrize(
    "operation,change",
    [("get", "project"), ("replay", "owner"), ("save", "owner"), ("save", "project")],
)
def test_access_is_rechecked_after_waiting_for_scope_lock(run_world, operation, change):
    service, world = api(), run_world
    engine = world["engine"]
    document_id, original = stored(world)
    with bounded_connections(engine), observe_backend(engine) as (started, backend):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with engine.begin() as blocker:
                table = "projects" if change == "owner" else "docx_documents"
                key = world["projects"]["own"] if change == "owner" else document_id
                blocker.execute(
                    text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE"), {"id": key}
                )
                future = executor.submit(command, world, document_id, operation)
                wait_for_lock(engine, started, backend)
                assert not future.done()
                if change == "owner":
                    blocker.execute(
                        text("UPDATE projects SET owner_id=:owner WHERE id=:id"),
                        {"owner": world["owners"]["foreign"], "id": key},
                    )
                else:
                    blocker.execute(
                        text("UPDATE docx_documents SET project_id=:project WHERE id=:id"),
                        {"project": world["projects"]["peer"], "id": key},
                    )
            reject(lambda: future.result(timeout=10), 404, "not_found")
    runtime = (
        replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
        if change == "owner"
        else world["runtimes"]["peer"]
    )
    assert service.get_docx(runtime, document_id=document_id) == original


def test_save_clock_is_evaluated_after_waiting_and_final_bigint_revision_is_readable(run_world):
    service, world = api(), run_world
    engine, runtime = world["engine"], world["runtimes"]["own"]
    document_id, original = stored(world)
    maximum = 9223372036854775807
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE docx_documents SET storage_revision=:revision WHERE id=:id"),
            {"revision": maximum - 1, "id": document_id},
        )
    with bounded_connections(engine), observe_backend(engine) as (started, backend):
        with ThreadPoolExecutor(max_workers=1) as executor:
            with engine.begin() as blocker:
                blocker.execute(
                    text("SELECT id FROM docx_documents WHERE id=:id FOR UPDATE"),
                    {"id": document_id},
                )
                future = executor.submit(
                    service.save_docx,
                    runtime,
                    document_id=document_id,
                    expected_storage_revision=maximum - 1,
                    data=original.current_data,
                )
                wait_for_lock(engine, started, backend)
                before_release = blocker.scalar(text("SELECT clock_timestamp()"))
            saved = future.result(timeout=10)
    with engine.connect() as connection:
        after = connection.scalar(text("SELECT clock_timestamp()"))
    assert saved.storage_revision == maximum
    assert before_release <= saved.updated_at <= after
    assert service.get_docx(runtime, document_id=document_id) == saved
    assert service.list_docx(runtime)[0].storage_revision == maximum
    reject(
        lambda: service.save_docx(
            runtime, document_id=document_id, expected_storage_revision=maximum, data=raw("later")
        ),
        422,
        "validation_error",
    )
    assert service.get_docx(runtime, document_id=document_id) == saved
