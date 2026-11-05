"""Frozen D02-07 acceptance: scoped binary downloads and metadata over HTTP."""

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from docx_storage_fixtures import api, raw
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FIELDS = {
    "document_id",
    "title",
    "storage_revision",
    "current_sha256",
    "current_size_bytes",
    "created_at",
    "updated_at",
}
MAX = 9223372036854775807


def client(runtime):
    return TestClient(
        import_module("ara.app").create_app(document_runtime=runtime), raise_server_exceptions=False
    )


def seed(world, scope="own", data=None):
    return api().import_docx(
        world["runtimes"][scope],
        document_id=uuid4(),
        title='  Требования "draft" 🧪  ',
        data=raw() if data is None else data,
    )


def path(item, suffix=""):
    return f"/docx-documents/{item.document_id}{suffix}"


def summary(response, item):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == FIELDS
    assert payload["document_id"] == str(item.document_id)
    assert payload["title"] == item.title
    assert type(payload["storage_revision"]) is int
    assert payload["storage_revision"] == item.storage_revision
    assert payload["current_sha256"] == item.current_sha256
    assert payload["current_size_bytes"] == len(item.current_data)
    for key in ("created_at", "updated_at"):
        assert datetime.fromisoformat(payload[key]) == getattr(item, key)
    assert response.headers["Cache-Control"] == "no-store"
    return payload


def error(response, status, code):
    assert response.status_code == status, response.text
    payload = response.json()
    assert set(payload) == {"code", "message", "retryable", "request_id"}
    assert payload["code"] == code
    assert payload["retryable"] is (status == 503)
    assert str(UUID(payload["request_id"])) == payload["request_id"]
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    assert "SELECT" not in response.text and "Traceback" not in response.text
    return payload


def test_metadata_download_save_reopen_and_no_writes(run_world):
    world = run_world
    source = Path("tests/fixtures/docx/rich-source.docx").read_bytes()
    item = seed(world, data=source)
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    event.listen(world["engine"], "before_cursor_execute", observe)
    try:
        with client(world["runtimes"]["own"]) as http:
            summary(http.get(path(item)), item)
            response = http.get(
                path(item, "/content"),
                headers={"Range": "bytes=0-9", "If-None-Match": '"anything"'},
            )
            assert response.status_code == 200
            assert response.content == source
            assert response.headers["content-type"] == MIME
            assert response.headers["content-disposition"] == (
                f'attachment; filename="{item.document_id}.docx"'
            )
            assert response.headers["content-length"] == str(len(source))
            assert response.headers["etag"] == '"' + sha256(source).hexdigest() + '"'
            assert response.headers["x-ara-storage-revision"] == "1"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    finally:
        event.remove(world["engine"], "before_cursor_execute", observe)
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "MERGE")) for s in statements)
    changed = api().save_docx(
        world["runtimes"]["own"],
        document_id=item.document_id,
        expected_storage_revision=1,
        data=raw("changed"),
    )
    engine = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with client(replace(world["runtimes"]["own"], engine=engine)) as http:
            summary(http.get(path(changed)), changed)
            response = http.get(path(changed, "/content"))
            assert response.content == changed.current_data != source
            assert response.headers["x-ara-storage-revision"] == "2"
            assert response.headers["etag"] == f'"{changed.current_sha256}"'
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()


def test_list_order_pagination_scope_and_metadata_only(run_world):
    world = run_world
    a, b = seed(world), seed(world)
    peer = seed(world, "peer")
    seed(world, "foreign")
    with client(world["runtimes"]["own"]) as http:
        response = http.get("/docx-documents")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()) == {"items"}
        items = response.json()["items"]
        assert [i["document_id"] for i in items] == [str(b.document_id), str(a.document_id)]
        assert all(set(i) == FIELDS for i in items)
        assert http.get("/docx-documents?limit=01&offset=01").json() == {"items": [items[1]]}
        assert http.get(f"/docx-documents?offset={MAX}").json() == {"items": []}
        for suffix in ("", "/content"):
            missing = error(http.get(f"/docx-documents/{uuid4()}{suffix}"), 404, "not_found")
            hidden = error(http.get(path(peer, suffix)), 404, "not_found")
            assert missing["message"] == hidden["message"]
            assert missing["request_id"] != hidden["request_id"]
    # A metadata list must not validate corrupt binary packages.
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE docx_documents SET current_data=:data WHERE id=:id"),
            {"data": b"corrupt", "id": a.document_id},
        )
    with client(world["runtimes"]["own"]) as http:
        assert http.get("/docx-documents").status_code == 200
        for suffix in ("", "/content"):
            error(http.get(path(a, suffix)), 500, "storage_error")


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        f"offset={MAX + 1}",
        "offset=1.0",
        "offset=1e2",
        "offset=+1",
        "offset=%2B1",
        "offset=%201",
        "offset=",
        "limit=1&limit=2",
        "offset=1&offset=2",
        "unknown=1",
        "offset=١",
        "offset=" + "0" * 20,
    ],
)
def test_invalid_list_query_before_db(run_world, query, monkeypatch):
    import ara.docx_documents as service

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid request reached service")

    monkeypatch.setattr(service, "list_docx", forbidden)
    with client(run_world["runtimes"]["own"]) as http:
        response = http.get("/docx-documents?" + query)
        payload = error(response, 422, "validation_error")
        assert payload["message"] == "Invalid request"


@pytest.mark.parametrize("suffix", ["", "/content"])
def test_invalid_uuid_queries_and_non_get(run_world, suffix):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        error(http.get("/docx-documents/not-a-uuid" + suffix), 422, "validation_error")
        error(http.get(path(item, suffix) + "?unknown=secret"), 422, "validation_error")
        assert http.post(path(item, suffix)).status_code == 405
        assert http.get(f"/docx-documents/{item.document_id.hex}{suffix}").status_code == 200


def test_safe_storage_failure_and_server_owned_scope(run_world, monkeypatch):
    import ara.docx_documents as service
    from ara.documents.storage import DocumentError

    def unavailable(*args, **kwargs):
        raise DocumentError(503, "storage_unavailable", "Document storage is unavailable", True)

    item = seed(run_world)
    monkeypatch.setattr(service, "get_docx", unavailable)
    monkeypatch.setattr(service, "list_docx", unavailable)
    with client(run_world["runtimes"]["own"]) as http:
        for target in ("/docx-documents", path(item), path(item, "/content")):
            error(http.get(target), 503, "storage_unavailable")


def test_factory_openapi_and_bigint_bounds(run_world):
    from ara.app import create_app

    with TestClient(create_app()) as http:
        assert http.get("/docx-documents").status_code == 404
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    schema = app.openapi()
    assert schema == app.openapi()
    paths = schema["paths"]
    assert set(paths["/docx-documents"]) == {"get"}
    for target in (
        "/docx-documents",
        "/docx-documents/{document_id}",
        "/docx-documents/{document_id}/content",
    ):
        expected_methods = {"get", "put"} if target.endswith("/content") else {"get"}
        assert set(paths[target]) == expected_methods
        assert {"200", "404", "422", "500", "503"} <= set(paths[target]["get"]["responses"])
    parameters = {p["name"]: p["schema"] for p in paths["/docx-documents"]["get"]["parameters"]}
    assert parameters["limit"]["default"] == 50
    assert parameters["limit"]["maximum"] == 100
    assert parameters["offset"]["default"] == 0
    assert type(parameters["offset"]["maximum"]) is int
    assert parameters["offset"]["maximum"] == MAX
    content = paths["/docx-documents/{document_id}/content"]["get"]["responses"]["200"]["content"]
    assert content[MIME]["schema"] == {"type": "string", "format": "binary"}
    assert "/documents/{document_id}/draft" in paths and "/health" in paths
