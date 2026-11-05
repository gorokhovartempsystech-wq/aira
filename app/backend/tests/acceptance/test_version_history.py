"""Independent acceptance for transactional, owner-scoped version append."""

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

PRIVATE = "SYNTHETIC_PRIVATE_HISTORY_84ea"


@pytest.fixture
def history_world(pg_engine):
    ids = {key: uuid4() for key in ("user", "other_user", "project", "peer", "foreign")}
    with pg_engine.begin() as connection:
        for key in ("user", "other_user"):
            connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": ids[key]})
        for project, user in (("project", "user"), ("peer", "user"), ("foreign", "other_user")):
            connection.execute(
                text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'Synthetic')"),
                {"id": ids[project], "owner": ids[user]},
            )
    runtime_class = import_module("ara.documents.runtime").DocumentRuntime
    return {
        key: runtime_class(engine=pg_engine, user_id=ids[user], project_id=ids[key], mode="local")
        for key, user in (("project", "user"), ("peer", "user"), ("foreign", "other_user"))
    }


def _client(runtime):
    factory = import_module("ara.app").create_app
    return TestClient(factory(document_runtime=runtime), raise_server_exceptions=False)


def _create(runtime):
    with _client(runtime) as client:
        response = client.post(
            "/documents", json={"title": "  Original title  ", "content_markdown": "# First\n"}
        )
        assert response.status_code == 201, response.text
        saved = response.json()
    return UUID(saved["id"]), UUID(saved["current_version_id"])


def _append(runtime, document, expected, content):
    append = import_module("ara.documents.storage").append_version
    return append(
        runtime, document_id=document, expected_version_id=expected, content_markdown=content
    )


def _read(runtime, document, version):
    with _client(runtime) as client:
        response = client.get(f"/documents/{document}/versions/{version}")
        assert response.status_code == 200, response.text
        return response.json()


def _state(engine):
    with engine.connect() as connection:
        return {
            table: [
                dict(row)
                for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
            ]
            for table in ("documents", "document_versions")
        }


def _failure(operation, status, code, retryable=False):
    error_type = import_module("ara.documents.api").DocumentError
    with pytest.raises(error_type) as caught:
        operation()
    error = caught.value
    assert (error.status, error.code, error.retryable) == (status, code, retryable)
    assert isinstance(error.message, str) and error.message
    assert PRIVATE not in error.message
    assert PRIVATE not in str(error)
    return error


def test_three_version_chain_and_returned_copy_preserve_all_http_snapshots(
    pg_engine, history_world
):
    runtime = history_world["project"]
    document, first_id = _create(runtime)
    first = _read(runtime, document, first_id)
    with pg_engine.begin() as connection:
        connection.execute(
            text("UPDATE documents SET source_url = :url WHERE id = :id"),
            {"id": document, "url": "https://example.invalid/synthetic"},
        )
    second_text = "## Второй\r\n\r\n```json\r\n{}\r\n```"
    second = _append(runtime, document, first_id, second_text)
    second_snapshot = second.model_dump(mode="json")
    assert second.document_id == document
    assert second.parent_version_id == first_id
    assert second.content_markdown == second_text
    assert "".join(block["text"] for block in second.blocks) == second_text
    assert {block["kind"] for block in second.blocks} == {"heading", "code"}
    assert next(block["text"] for block in second.blocks if block["kind"] == "code").strip() == (
        "```json\r\n{}\r\n```"
    )
    assert second.provenance == {"source": "manual"}
    assert second.import_omissions == []
    third_text = "Third paragraph\n\n~~~python\nunfinished\n"
    third = _append(runtime, document, second.id, third_text)
    assert third.parent_version_id == second.id
    assert third.content_markdown == third_text
    assert "".join(block["text"] for block in third.blocks) == third_text
    unsupported = [block for block in third.blocks if block["kind"] == "unsupported"]
    assert len(unsupported) == 1
    assert len(third.import_omissions) == 1
    assert third.import_omissions[0]["block_id"] == unsupported[0]["id"]
    assert isinstance(third.import_omissions[0]["reason"], str)
    assert third.import_omissions[0]["reason"]
    assert len({first_id, second.id, third.id}) == 3
    third_snapshot = third.model_dump(mode="json")
    second.blocks[0]["text"] = PRIVATE
    second.provenance["mutated"] = PRIVATE
    second.import_omissions.append(PRIVATE)
    replacement = create_engine(pg_engine.url, poolclass=NullPool, hide_parameters=True)
    try:
        runtime_class = import_module("ara.documents.runtime").DocumentRuntime
        fresh = runtime_class(
            engine=replacement, user_id=runtime.user_id, project_id=runtime.project_id, mode="local"
        )
        for version_id, expected in (
            (first_id, first),
            (second.id, second_snapshot),
            (third.id, third_snapshot),
        ):
            assert _read(fresh, document, version_id) == expected
    finally:
        replacement.dispose()
    state = _state(pg_engine)
    assert len(state["document_versions"]) == 3
    assert state["documents"][0]["current_version_id"] == third.id
    assert state["documents"][0]["title"] == "  Original title  "
    assert state["documents"][0]["source_url"] == "https://example.invalid/synthetic"


def test_access_precedes_conflict_and_foreign_history_remains_unchanged(pg_engine, history_world):
    runtime = history_world["project"]
    own_document, own_version = _create(runtime)
    outside = [_create(history_world[key]) for key in ("peer", "foreign")]
    runtime_class = import_module("ara.documents.runtime").DocumentRuntime
    wrong_owner = runtime_class(
        engine=pg_engine,
        user_id=history_world["foreign"].user_id,
        project_id=runtime.project_id,
        mode="local",
    )
    before = _state(pg_engine)
    errors = []
    for document, version in [*outside, (uuid4(), uuid4())]:
        for expected in (version, uuid4()):
            errors.append(
                _failure(lambda: _append(runtime, document, expected, PRIVATE), 404, "not_found")
            )
    errors.append(
        _failure(lambda: _append(wrong_owner, own_document, own_version, PRIVATE), 404, "not_found")
    )
    with _client(runtime) as client:
        missing = client.get(f"/documents/{uuid4()}/versions/{uuid4()}").json()
    assert all(error.message == missing["message"] for error in errors)
    assert _state(pg_engine) == before


def test_stale_and_repeated_base_conflict_without_another_version(pg_engine, history_world):
    runtime = history_world["project"]
    document, first = _create(runtime)
    second = _append(runtime, document, first, "Second\n")
    _, foreign_version = _create(history_world["foreign"])
    _, peer_version = _create(history_world["peer"])
    before = _state(pg_engine)
    for expected in (first, first, uuid4(), foreign_version, peer_version):
        error = _failure(
            lambda: _append(runtime, document, expected, PRIVATE), 409, "version_conflict"
        )
        assert str(second.id) not in error.message
    assert _state(pg_engine) == before


def test_direct_append_strictly_validates_ids_and_text_without_writing(pg_engine, history_world):
    runtime = history_world["project"]
    document, first = _create(runtime)
    before = _state(pg_engine)
    invalid_calls = [
        (str(document), first, "text"),
        (None, first, "text"),
        (document, str(first), "text"),
        (document, 7, "text"),
    ]
    invalid_calls.extend(
        (document, first, content)
        for content in (None, 7, True, ["text"], "", " \r\n", "x\x00y", "\ud800", "x" * 1_000_001)
    )
    for target, expected, content in invalid_calls:
        _failure(lambda: _append(runtime, target, expected, content), 422, "validation_error")
    assert _state(pg_engine) == before


@pytest.mark.parametrize("failure_step", ["version_insert", "current_update"])
def test_append_write_failures_preserve_current_and_previous_history(
    pg_engine, history_world, failure_step
):
    runtime = history_world["project"]
    document, first = _create(runtime)
    before = _state(pg_engine)
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION ara_test_reject_append() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN RAISE EXCEPTION '{PRIVATE}'; END $$"
            )
        )
        target = (
            "BEFORE INSERT ON document_versions"
            if failure_step == "version_insert"
            else "BEFORE UPDATE OF current_version_id ON documents"
        )
        connection.execute(
            text(
                f"CREATE TRIGGER ara_test_append_failure {target} "
                "FOR EACH ROW EXECUTE FUNCTION ara_test_reject_append()"
            )
        )
    _failure(lambda: _append(runtime, document, first, PRIVATE), 500, "storage_error")
    assert _state(pg_engine) == before


def test_append_operational_error_is_safe_retryable_503(pg_engine, history_world):
    runtime = history_world["project"]
    document, first = _create(runtime)
    before = _state(pg_engine)

    def unavailable(*args, **kwargs):
        raise OperationalError(PRIVATE, {"private": PRIVATE}, Exception(PRIVATE))

    event.listen(pg_engine, "before_cursor_execute", unavailable)
    try:
        _failure(
            lambda: _append(runtime, document, first, PRIVATE), 503, "storage_unavailable", True
        )
    finally:
        event.remove(pg_engine, "before_cursor_execute", unavailable)
    assert _state(pg_engine) == before


def test_concurrent_writers_with_one_base_create_exactly_one_child(pg_engine, history_world):
    runtime = history_world["project"]
    document, first = _create(runtime)
    append = import_module("ara.documents.storage").append_version
    error_type = import_module("ara.documents.api").DocumentError
    barrier = Barrier(2)

    def bounded_connection(dbapi_connection, connection_record):
        original = dbapi_connection.autocommit
        dbapi_connection.autocommit = True
        try:
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
        finally:
            dbapi_connection.autocommit = original

    def write(content):
        barrier.wait(timeout=5)
        try:
            return append(
                runtime, document_id=document, expected_version_id=first, content_markdown=content
            )
        except error_type as error:
            return error

    event.listen(pg_engine, "connect", bounded_connection)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(write, content) for content in ("Writer A", "Writer B")]
            results = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(pg_engine, "connect", bounded_connection)
    successes = [result for result in results if not isinstance(result, error_type)]
    failures = [result for result in results if isinstance(result, error_type)]
    assert len(successes) == len(failures) == 1
    assert (failures[0].status, failures[0].code, failures[0].retryable) == (
        409,
        "version_conflict",
        False,
    )
    state = _state(pg_engine)
    assert len(state["document_versions"]) == 2
    winner = successes[0]
    assert winner.parent_version_id == first
    assert state["documents"][0]["current_version_id"] == winner.id
    assert _read(runtime, document, winner.id)["content_markdown"] == winner.content_markdown
