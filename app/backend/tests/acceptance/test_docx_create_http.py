"""Frozen D03-10 acceptance: new blank documents with scoped replay and safe HTTP."""

import importlib
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from test_docx_http_reads import client, error, summary

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
from ara.docx_documents import get_docx, import_docx, save_docx
from ara.docx_package.creation import create_docx
from ara.docx_package.projection import project_docx

ROOT = Path(__file__).resolve().parents[2]
ROUTE = "/docx-documents/{document_id}/create"


def create(http, identity, title="Synthetic new document"):
    return http.post(ROUTE.format(document_id=identity), params={"title": title})


def test_create_edit_download_and_replay_preserve_current_and_original(run_world):
    from ara.docx_package.editing import TextEdit, export_docx

    runtime = run_world["runtimes"]["own"]
    identity, title = uuid4(), '  Новые требования "😀"  '
    with client(runtime) as http:
        response = create(http, identity, title)
        first = get_docx(runtime, document_id=identity)
        original_metadata = summary(response, first)
        assert first.title == title and first.storage_revision == 1
        assert first.original_data == first.current_data == create_docx()
        assert [p.text for p in project_docx(first.current_data).blocks] == [""]
        download = http.get(f"/docx-documents/{identity}/content")
        assert download.content == create_docx()
        span = project_docx(first.current_data).blocks[0].spans[0]
        edited = export_docx(
            first.current_data, (TextEdit(span.anchor, "", "Edited new document"),)
        )
        saved = save_docx(runtime, document_id=identity, expected_storage_revision=1, data=edited)
        replay = summary(create(http, identity, title), saved)
        assert (
            replay["storage_revision"] == 2
            and replay["created_at"] == original_metadata["created_at"]
        )
        assert get_docx(runtime, document_id=identity) == saved
        assert http.get(f"/docx-documents/{identity}/content").content == edited


def test_concurrent_replays_create_one_row(run_world):
    runtime = run_world["runtimes"]["own"]
    identity, barrier = uuid4(), threading.Barrier(2)

    def send(_):
        with client(runtime) as http:
            barrier.wait(timeout=5)
            return create(http, identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, (0, 1)))
    assert responses[0].status_code == responses[1].status_code == 200
    assert responses[0].json() == responses[1].json()
    with runtime.engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM docx_documents WHERE id=:id"), {"id": identity}
            )
            == 1
        )


def test_lost_ack_replay_is_same_row_timestamp_and_revision(run_world):
    from starlette.responses import JSONResponse

    runtime, identity = run_world["runtimes"]["own"], uuid4()
    app, dropped = create_app(document_runtime=runtime), False

    @app.middleware("http")
    async def drop_ack(request, call_next):
        nonlocal dropped
        response = await call_next(request)
        if request.method == "POST" and request.url.path.endswith("/create") and not dropped:
            dropped = True
            return JSONResponse({"code": "synthetic_lost_ack"}, status_code=503)
        return response

    with TestClient(app) as http:
        assert create(http, identity).status_code == 503
        saved = get_docx(runtime, document_id=identity)
        summary(create(http, identity), saved)
        assert get_docx(runtime, document_id=identity) == saved


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_foreign_scope_ids_remain_hidden(run_world, scope):
    foreign = import_docx(
        run_world["runtimes"][scope], document_id=uuid4(), title="Hidden", data=create_docx()
    )
    with client(run_world["runtimes"]["own"]) as http:
        error(create(http, foreign.document_id, "Hidden"), 404, "not_found")
    assert get_docx(run_world["runtimes"][scope], document_id=foreign.document_id) == foreign


def test_title_or_original_mismatch_conflicts_without_changes(run_world):
    from docx_storage_fixtures import raw

    runtime = run_world["runtimes"]["own"]
    item = import_docx(runtime, document_id=uuid4(), title="Original", data=create_docx())
    other = import_docx(runtime, document_id=uuid4(), title="Original", data=raw())
    with client(runtime) as http:
        error(create(http, item.document_id, "Other"), 409, "creation_conflict")
        error(create(http, other.document_id, "Original"), 409, "creation_conflict")
    assert get_docx(runtime, document_id=item.document_id) == item
    assert get_docx(runtime, document_id=other.document_id) == other


@pytest.fixture
def no_storage(monkeypatch):
    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    engine = create_engine("postgresql+psycopg://")

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid request accessed storage")

    monkeypatch.setattr(engine, "connect", forbidden)
    monkeypatch.setattr(importlib.import_module("ara.docx_documents"), "import_docx", forbidden)
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    yield runtime
    engine.dispose()


def no_generation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid request generated a document")

    monkeypatch.setattr(
        importlib.import_module("ara.docx_package.creation"), "create_docx", forbidden
    )


@pytest.mark.parametrize(
    "query",
    [
        "",
        "title=",
        "title=%20%09",
        "title=a&title=b",
        "title=a&owner_id=forged",
        "title=a%00b",
        "title=" + "x" * 201,
        "title=%ED%A0%80",
    ],
)
def test_invalid_query_never_generates_or_stores(no_storage, monkeypatch, query):
    no_generation(monkeypatch)
    with client(no_storage) as http:
        error(http.post(ROUTE.format(document_id=uuid4()) + "?" + query), 422, "validation_error")


@pytest.mark.parametrize("identity", ["not-a-uuid", "123", "none"])
def test_invalid_uuid_never_generates_or_stores(no_storage, monkeypatch, identity):
    no_generation(monkeypatch)
    with client(no_storage) as http:
        error(create(http, identity), 422, "validation_error")


@pytest.mark.parametrize(
    "headers,body,status,code",
    [
        ({"Content-Type": "application/json"}, b"", 415, "unsupported_media_type"),
        ({"Content-Encoding": "gzip"}, b"", 415, "unsupported_media_type"),
        ({"Content-Length": "1"}, b"", 422, "validation_error"),
        ({"Content-Length": "-1"}, b"", 422, "validation_error"),
        ({"Content-Length": "0" * 20}, b"", 422, "validation_error"),
        ({"Transfer-Encoding": "chunked"}, b"", 422, "validation_error"),
        ({"Content-Length": "0"}, b"unexpected", 422, "validation_error"),
        ({}, b"unexpected", 422, "validation_error"),
        ([("Content-Length", "0"), ("Content-Length", "0")], b"", 422, "validation_error"),
        ([("Content-Type", ""), ("Content-Type", "")], b"", 422, "validation_error"),
        (
            [("Content-Encoding", "identity"), ("Content-Encoding", "identity")],
            b"",
            422,
            "validation_error",
        ),
    ],
)
def test_transport_rejects_before_generation_or_storage(
    no_storage, monkeypatch, headers, body, status, code
):
    no_generation(monkeypatch)
    with client(no_storage) as http:
        error(
            http.post(
                ROUTE.format(document_id=uuid4()),
                params={"title": "Valid"},
                headers=headers,
                content=body,
            ),
            status,
            code,
        )


@pytest.mark.parametrize("kind", ["creation", "package", "projection"])
def test_generator_errors_are_safe_and_do_not_reach_storage(no_storage, monkeypatch, kind):
    from ara.docx_package import DocxError
    from ara.docx_package.creation import CreationError
    from ara.docx_package.projection import ProjectionError

    exception = {
        "creation": CreationError("invalid_input"),
        "package": DocxError("invalid_package"),
        "projection": ProjectionError("invalid_input"),
    }[kind]

    def fail():
        raise exception

    monkeypatch.setattr(importlib.import_module("ara.docx_package.creation"), "create_docx", fail)
    with client(no_storage) as http:
        response = create(http, uuid4())
        payload = error(response, 500, "creation_error")
        assert payload["message"] == "Document could not be created"


def test_default_factory_openapi_and_accessible_new_document_form(no_storage, monkeypatch):
    no_generation(monkeypatch)
    with TestClient(create_app()) as default:
        assert create(default, uuid4()).status_code == 404
    with client(no_storage) as http:
        schema = http.get("/openapi.json").json()
        route = schema["paths"][ROUTE]
        assert set(route) == {"post"}
        definition = route["post"]
        assert "requestBody" not in definition
        assert {"200", "404", "409", "415", "422", "500", "503"} <= set(definition["responses"])
        assert {p["name"] for p in definition["parameters"]} == {"document_id", "title"}

        class Page(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []

            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))

        page = Page()
        page.feed(http.get("/workspace").text)
        assert any(t == "form" and a.get("id") == "create-form" for t, a in page.tags)
        assert any(t == "label" and a.get("for") == "create-name" for t, a in page.tags)
        assert any(t == "input" and a.get("id") == "create-name" for t, a in page.tags)
        assert any(t == "dialog" and a.get("id") == "create-reset-dialog" for t, a in page.tags)


def test_create_transport_module_import_is_inert():
    script = """
import builtins, io, importlib, os, socket, subprocess
from pathlib import Path
import psycopg, sqlalchemy
def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected external I/O")
for obj,name in ((builtins,"open"),(io,"open"),(Path,"read_bytes"),(Path,"read_text"),
                 (os,"getenv"),(socket,"socket"),(subprocess,"Popen"),
                 (psycopg,"connect"),(sqlalchemy,"create_engine")):
    setattr(obj,name,forbidden)
importlib.import_module("ara.docx_documents.create_http")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
