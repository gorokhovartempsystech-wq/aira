"""Extra D03-10 stream boundaries, worker-thread execution and error handling."""

import asyncio
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from starlette.responses import JSONResponse

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError
from ara.docx_documents.create_http import install_docx_creation


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    engine = create_engine("postgresql+psycopg://")
    yield DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    engine.dispose()


def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected generator or storage call")


@pytest.mark.parametrize("query", ["title=%", "title=%ZZ", "title=%FF", "title=a&"])
def test_bad_uri_encoding_rejected_without_silent_replacement(runtime, monkeypatch, query):
    monkeypatch.setattr("ara.docx_package.creation.create_docx", forbidden)
    monkeypatch.setattr("ara.docx_documents.import_docx", forbidden)
    with TestClient(create_app(document_runtime=runtime)) as http:
        response = http.post(f"/docx-documents/{uuid4()}/create?{query}")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize("disconnect", [False, True])
def test_stream_stops_on_first_nonempty_chunk_or_disconnect(runtime, monkeypatch, disconnect):
    monkeypatch.setattr("ara.docx_package.creation.create_docx", forbidden)
    monkeypatch.setattr("ara.docx_documents.import_docx", forbidden)
    app = FastAPI()
    install_docx_creation(app, runtime)

    @app.exception_handler(DocumentError)
    async def error(request, exception):
        return JSONResponse({"code": exception.code}, status_code=exception.status)

    count, messages = 0, []

    async def receive():
        nonlocal count
        count += 1
        assert count == 1, "Route drained an unwanted request body"
        return (
            {"type": "http.disconnect"}
            if disconnect
            else {"type": "http.request", "body": b"x" * 1048576, "more_body": True}
        )

    async def send(message):
        messages.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": f"/docx-documents/{uuid4()}/create",
                "query_string": b"title=Synthetic",
                "headers": [],
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 1234),
                "root_path": "",
            },
            receive,
            send,
        )
    )
    assert count == 1
    assert next(m for m in messages if m["type"] == "http.response.start")["status"] == 422


def test_generation_and_storage_run_off_event_loop_and_keep_literal_title(runtime, monkeypatch):
    event_threads, worker_threads = [], []
    raw = b"synthetic template sentinel"

    def generate():
        worker_threads.append(threading.get_ident())
        return raw

    def store(supplied_runtime, *, document_id, title, data):
        worker_threads.append(threading.get_ident())
        assert supplied_runtime is runtime and data is raw and title == "  A � 😀  "
        return SimpleNamespace(
            document_id=document_id,
            title=title,
            storage_revision=1,
            current_sha256="0" * 64,
            current_data=data,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    monkeypatch.setattr("ara.docx_package.creation.create_docx", generate)
    monkeypatch.setattr("ara.docx_documents.import_docx", store)
    app = create_app(document_runtime=runtime)

    @app.middleware("http")
    async def observe(request, call_next):
        event_threads.append(threading.get_ident())
        return await call_next(request)

    with TestClient(app) as http:
        response = http.post(f"/docx-documents/{uuid4()}/create", params={"title": "  A � 😀  "})
    assert response.status_code == 200
    assert response.json()["title"] == "  A � 😀  "
    assert len(worker_threads) == 2 and not set(worker_threads) & set(event_threads)


@pytest.mark.parametrize("status,code", [(500, "storage_error"), (503, "storage_unavailable")])
def test_storage_errors_keep_existing_envelope(runtime, monkeypatch, status, code):
    def fail(*args, **kwargs):
        raise DocumentError(
            status, code, "Document storage operation failed", retryable=status == 503
        )

    monkeypatch.setattr("ara.docx_documents.import_docx", fail)
    with TestClient(create_app(document_runtime=runtime)) as http:
        response = http.post(f"/docx-documents/{uuid4()}/create", params={"title": "Synthetic"})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["retryable"] is (status == 503)
