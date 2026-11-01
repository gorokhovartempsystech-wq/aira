"""Invalid requests and application construction must never open storage."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime


@pytest.fixture
def isolated_client(monkeypatch):
    engine = create_engine("postgresql+psycopg://synthetic@localhost/unused")

    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected database access or disposal of caller-owned engine")

    with monkeypatch.context() as patches:
        patches.setattr(engine, "connect", forbidden)
        patches.setattr(engine, "dispose", forbidden)
        runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
        with TestClient(create_app(document_runtime=runtime)) as client:
            yield client
    engine.dispose()


@pytest.mark.parametrize(
    "body",
    [
        b'{"title": "SYNTHETIC_PRIVATE",',
        b'{"title": "\xff", "content_markdown": "text"}',
        b"null",
        b"[]",
        b'{"title": true, "content_markdown": "text"}',
        b'{"title": "text", "content_markdown": false}',
    ],
)
def test_malformed_requests_have_safe_unique_errors_without_storage(isolated_client, body):
    request_ids = set()
    for _ in range(2):
        response = isolated_client.post(
            "/documents",
            content=body,
            headers={"Content-Type": "application/json", "X-Request-ID": "client-controlled"},
        )
        assert response.status_code == 422
        assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
        error = response.json()
        assert set(error) == {"code", "message", "retryable", "request_id"}
        assert error["code"] == "validation_error"
        assert error["retryable"] is False
        assert "SYNTHETIC_PRIVATE" not in response.text
        assert error["request_id"] != "client-controlled"
        request_ids.add(error["request_id"])
    assert len(request_ids) == 2


def test_explicit_runtime_keeps_health_and_openapi_inert(isolated_client):
    assert isolated_client.get("/health").json() == {"status": "ok"}
    schema = isolated_client.get("/openapi.json").json()
    assert "not real authentication" in schema["info"]["description"]
    assert "local-dev" in schema["info"]["description"]
    assert set(schema["paths"]) == {
        "/health",
        "/me",
        "/documents/{document_id}/runs",
        "/runs/{run_id}",
        "/runs/{run_id}/review",
        "/documents",
        "/documents/{document_id}/versions/{version_id}",
        "/documents/{document_id}/draft",
        "/docx-documents",
        "/docx-documents/{document_id}",
        "/docx-documents/{document_id}/content",
        "/docx-documents/{document_id}/import",
        "/docx-documents/{document_id}/view",
        "/docx-documents/{document_id}/text-edit",
        "/docx-documents/{document_id}/draft",
        "/docx-documents/{document_id}/create",
        "/docx-documents/{document_id}/paragraph-commands",
        "/docx-documents/{document_id}/editor-recovery",
        "/docx-documents/{document_id}/editor-recovery/content",
        "/docx-documents/{document_id}/editor-recovery/prepare-discard",
        "/docx-documents/{document_id}/editor-recovery/discard",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/saved-content",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/working-content",
        "/docx-documents/{document_id}/editor-sessions",
        "/docx-documents/{document_id}/editor-sessions/{session_id}",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/view",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/commands",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/checkpoint",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/save",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/reconcile",
        "/docx-documents/{document_id}/editor-sessions/{session_id}/close",
    }
    assert set(schema["paths"]["/runs/{run_id}/review"]) == {"get", "put"}
    assert set(schema["paths"]["/documents/{document_id}/draft"]) == {"get", "put"}
