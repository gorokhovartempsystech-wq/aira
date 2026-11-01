"""Additional storage boundaries using synthetic data in disposable PostgreSQL."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError

from ara.app import create_app
from ara.documents.api import DocumentError
from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import append_version
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine


@pytest.fixture
def saved_document(pg_engine, monkeypatch):
    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    user, project = uuid4(), uuid4()
    with pg_engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": user})
        connection.execute(
            text("INSERT INTO projects (id, owner_id, name) VALUES (:id, :owner, 'Synthetic')"),
            {"id": project, "owner": user},
        )
    runtime = DocumentRuntime(engine=pg_engine, user_id=user, project_id=project, mode="local")
    with TestClient(create_app(document_runtime=runtime)) as client:
        response = client.post(
            "/documents", json={"title": "Synthetic", "content_markdown": "Initial\n"}
        )
        assert response.status_code == 201
    saved = response.json()
    return runtime, UUID(saved["id"]), UUID(saved["current_version_id"])


def test_invalid_append_does_not_connect_or_dispose_caller_engine(monkeypatch):
    engine = create_engine("postgresql+psycopg://synthetic@localhost/unused")
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid input must not access storage or dispose the caller's engine")

    try:
        with monkeypatch.context() as patches:
            patches.setattr(engine, "connect", forbidden)
            patches.setattr(engine, "dispose", forbidden)
            for content in (b"text", False, None, "\x00", "\ud800", " ", "x" * 1_000_001):
                with pytest.raises(DocumentError) as caught:
                    append_version(
                        runtime,
                        document_id=uuid4(),
                        expected_version_id=uuid4(),
                        content_markdown=content,
                    )
                assert (caught.value.status, caught.value.code, caught.value.retryable) == (
                    422,
                    "validation_error",
                    False,
                )
    finally:
        engine.dispose()


def test_append_reports_omissions_and_preserves_nested_returned_snapshot(saved_document):
    runtime, document, first = saved_document
    content = "# Synthetic\r\n\r\n```\r\nunclosed\r\n"
    second = append_version(
        runtime, document_id=document, expected_version_id=first, content_markdown=content
    )
    snapshot = second.model_dump(mode="json")
    assert "".join(block["text"] for block in second.blocks) == content
    assert second.import_omissions == [
        {"block_id": second.blocks[-1]["id"], "reason": "Unclosed fenced code block"}
    ]
    second.import_omissions[0]["reason"] = "Modified outside storage"
    with TestClient(create_app(document_runtime=runtime)) as client:
        assert client.get(f"/documents/{document}/versions/{second.id}").json() == snapshot
        assert client.get("/documents").json()["items"][0]["current_version_id"] == str(second.id)


def test_project_owner_cannot_change_during_append_and_is_rechecked_afterward(saved_document):
    runtime, document, first = saved_document
    other_user = uuid4()
    with runtime.engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": other_user})
    blocked = []

    def try_change_owner(connection, cursor, statement, parameters, context, executemany):
        if not statement.startswith("INSERT INTO document_versions"):
            return
        # A separate transaction must not change ownership while append is writing.
        with runtime.engine.connect() as outsider:
            outsider.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError) as caught:
                outsider.execute(
                    text("UPDATE projects SET owner_id = :owner WHERE id = :project"),
                    {"owner": other_user, "project": runtime.project_id},
                )
            assert caught.value.orig.sqlstate == "55P03"
            blocked.append(True)

    event.listen(runtime.engine, "before_cursor_execute", try_change_owner)
    try:
        second = append_version(
            runtime, document_id=document, expected_version_id=first, content_markdown="Second"
        )
    finally:
        event.remove(runtime.engine, "before_cursor_execute", try_change_owner)
    assert blocked == [True]
    with runtime.engine.begin() as connection:
        connection.execute(
            text("UPDATE projects SET owner_id = :owner WHERE id = :project"),
            {"owner": other_user, "project": runtime.project_id},
        )
    with pytest.raises(DocumentError) as caught:
        append_version(
            runtime, document_id=document, expected_version_id=first, content_markdown="Third"
        )
    assert (caught.value.status, caught.value.code) == (404, "not_found")
    with TestClient(create_app(document_runtime=runtime)) as client:
        for path in ("/me", "/documents", f"/documents/{document}/versions/{second.id}"):
            assert client.get(path).status_code == 404
    new_runtime = replace(runtime, user_id=other_user)
    with TestClient(create_app(document_runtime=new_runtime)) as client:
        assert client.get("/me").json()["user_id"] == str(other_user)
        assert client.get(f"/documents/{document}/versions/{first}").status_code == 200
        assert client.get(f"/documents/{document}/versions/{second.id}").status_code == 200


def test_commit_failure_returns_safe_error_and_rolls_back_both_writes(saved_document):
    runtime, document, first = saved_document

    def fail_commit(connection):
        raise OperationalError("SYNTHETIC_PRIVATE", {}, Exception("SYNTHETIC_PRIVATE"))

    event.listen(runtime.engine, "commit", fail_commit)
    try:
        with pytest.raises(DocumentError) as caught:
            append_version(
                runtime,
                document_id=document,
                expected_version_id=first,
                content_markdown="Uncommitted",
            )
        error = caught.value
        assert (error.status, error.code, error.retryable) == (503, "storage_unavailable", True)
        assert "SYNTHETIC_PRIVATE" not in str(error)
    finally:
        event.remove(runtime.engine, "commit", fail_commit)
    with runtime.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM document_versions")) == 1
        assert connection.scalar(text("SELECT current_version_id FROM documents")) == first
