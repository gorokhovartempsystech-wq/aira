"""Independent D02-08 acceptance, frozen before the write transport exists."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from docx_storage_fixtures import api, raw
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from test_docx_http_reads import MAX, MIME, client, error, summary

SIZE = 33554432


def target(identity, operation):
    tail = "/import" if operation == "post" else "/content"
    return f"/docx-documents/{identity}{tail}"


def upload(http, identity, data, *, title="Synthetic requirements"):
    return http.post(
        target(identity, "post"),
        params={"title": title},
        content=data,
        headers={"Content-Type": MIME},
    )


def save(http, identity, data, revision):
    return http.put(
        target(identity, "put"),
        params={"expected_storage_revision": revision},
        content=data,
        headers={"Content-Type": MIME},
    )


def test_full_http_roundtrip_session_recovery_and_exact_original(run_world):
    from ara.docx_package.ranges import RangeEdit, TextPosition
    from ara.docx_package.session import DocxSession

    world = run_world
    identity = uuid4()
    source = Path("tests/fixtures/docx/rich-source.docx").read_bytes()
    title = '  Требования "Я🧪"  '
    with client(world["runtimes"]["own"]) as http:
        imported = upload(http, identity, source, title=title)
        stored = api().get_docx(world["runtimes"]["own"], document_id=identity)
        before = summary(imported, stored)
        assert stored.original_data == stored.current_data == source
        session = DocxSession(source)
        paragraph = next(
            b
            for b in session.snapshot().projection.blocks
            if b.kind == "paragraph" and any(s.kind == "text" for s in b.spans)
        )
        span = next(s for s in paragraph.spans if s.kind == "text")
        changed = session.apply(
            (
                RangeEdit(
                    TextPosition(span.anchor, 0),
                    TextPosition(span.anchor, len(span.text)),
                    span.text,
                    "Updated " + span.text,
                ),
            ),
            expected_revision=0,
        )
        response = save(http, identity, changed.data, 1)
        saved = api().get_docx(world["runtimes"]["own"], document_id=identity)
        after = summary(response, saved)
        assert after["storage_revision"] == 2
        assert after["created_at"] == before["created_at"]
        assert saved.title == title and saved.original_data == source
        assert saved.current_data == changed.data != source
        assert session.snapshot().is_dirty
        assert not session.mark_saved(expected_revision=changed.revision).is_dirty
        assert summary(upload(http, identity, source, title=title), saved) == after
        error(upload(http, identity, raw("different"), title=title), 409, "import_conflict")
        error(upload(http, identity, source, title="different"), 409, "import_conflict")
        error(save(http, identity, changed.data, 1), 409, "docx_conflict")
    engine = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        runtime = replace(world["runtimes"]["own"], engine=engine)
        with client(runtime) as restarted:
            summary(restarted.get(f"/docx-documents/{identity}"), saved)
            downloaded = restarted.get(target(identity, "put"))
            assert downloaded.content == changed.data
            assert downloaded.headers["etag"] == f'"{sha256(changed.data).hexdigest()}"'
            reopened = DocxSession(downloaded.content).snapshot()
            assert reopened.revision == 0 and not reopened.is_dirty
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()


def test_concurrent_saves_have_one_winner_and_keep_original(run_world):
    world = run_world
    identity, source = uuid4(), raw()
    with client(world["runtimes"]["own"]) as http:
        assert upload(http, identity, source).status_code == 200
    barrier = threading.Barrier(2)

    def attempt(data):
        with client(world["runtimes"]["own"]) as http:
            barrier.wait(timeout=5)
            return data, save(http, identity, data, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (raw("first"), raw("second"))))
    assert sorted(r.status_code for _, r in results) == [200, 409]
    stored = api().get_docx(world["runtimes"]["own"], document_id=identity)
    winner = next(data for data, r in results if r.status_code == 200)
    assert stored.current_data == winner and stored.original_data == source
    assert stored.storage_revision == 2


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_foreign_ids_remain_hidden_and_unchanged(run_world, scope):
    world = run_world
    item = api().import_docx(
        world["runtimes"][scope], document_id=uuid4(), title="Hidden", data=raw()
    )
    with client(world["runtimes"]["own"]) as http:
        error(upload(http, item.document_id, raw(), title="Hidden"), 404, "not_found")
        error(save(http, item.document_id, raw("changed"), 1), 404, "not_found")
        error(save(http, uuid4(), raw(), 1), 404, "not_found")
    assert api().get_docx(world["runtimes"][scope], document_id=item.document_id) == item


@pytest.mark.parametrize(
    "operation,query",
    [
        ("post", ""),
        ("post", "title="),
        ("post", "title=%20%09"),
        ("post", "title=a&title=b"),
        ("post", "title=a&owner_id=forged"),
        ("post", "title=a%00b"),
        ("post", "title=" + "x" * 201),
        ("put", ""),
        ("put", "expected_storage_revision=0"),
        ("put", f"expected_storage_revision={MAX}"),
        ("put", "expected_storage_revision=-1"),
        ("put", "expected_storage_revision=1.0"),
        ("put", "expected_storage_revision=1e0"),
        ("put", "expected_storage_revision=%2B1"),
        ("put", "expected_storage_revision=%201"),
        ("put", "expected_storage_revision=١"),
        ("put", "expected_storage_revision=" + "0" * 20),
        ("put", "expected_storage_revision=1&expected_storage_revision=1"),
        ("put", "expected_storage_revision=1&title=forged"),
    ],
)
def test_invalid_queries_do_not_call_storage(run_world, monkeypatch, operation, query):
    service = api()

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid transport request reached storage")

    monkeypatch.setattr(service, "import_docx", forbidden)
    monkeypatch.setattr(service, "save_docx", forbidden)
    with client(run_world["runtimes"]["own"]) as http:
        response = http.request(
            operation,
            target(uuid4(), operation) + "?" + query,
            content=raw(),
            headers={"Content-Type": MIME},
        )
        payload = error(response, 422, "validation_error")
        assert payload["message"] == "Invalid request"


@pytest.mark.parametrize(
    "headers,status,code",
    [
        ({}, 415, "unsupported_media_type"),
        ({"Content-Type": "application/json"}, 415, "unsupported_media_type"),
        ({"Content-Type": MIME + "; charset=utf-8"}, 415, "unsupported_media_type"),
        ({"Content-Type": MIME, "Content-Encoding": "gzip"}, 415, "unsupported_media_type"),
        ({"Content-Type": MIME, "Content-Length": str(SIZE + 1)}, 413, "upload_too_large"),
        ({"Content-Type": MIME, "Content-Length": "-1"}, 422, "validation_error"),
        ({"Content-Type": MIME, "Content-Length": "+1"}, 422, "validation_error"),
        ({"Content-Type": MIME, "Content-Length": "1"}, 422, "validation_error"),
        ({"Content-Type": MIME, "Content-Length": "0" * 20}, 422, "validation_error"),
        (
            {"Content-Type": MIME, "Transfer-Encoding": "chunked", "Content-Length": "1"},
            422,
            "validation_error",
        ),
    ],
)
def test_transport_errors_are_safe_and_do_not_call_storage(
    run_world, monkeypatch, headers, status, code
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Bad transport reached storage")

    monkeypatch.setattr(api(), "import_docx", forbidden)
    with client(run_world["runtimes"]["own"]) as http:
        response = http.post(
            target(uuid4(), "post"), params={"title": "Synthetic"}, content=raw(), headers=headers
        )
        error(response, status, code)


@pytest.mark.parametrize("operation", ["post", "put"])
def test_bad_packages_never_change_persisted_file(run_world, operation):
    from ara.docx_package import DocxError
    from ara.docx_package.projection import project_docx

    world = run_world
    item = api().import_docx(
        world["runtimes"]["own"], document_id=uuid4(), title="Original", data=raw()
    )
    with client(world["runtimes"]["own"]) as http:
        for content in (b"", b"SYNTHETIC_PRIVATE_not_a_zip"):
            with pytest.raises(DocxError) as exc:
                project_docx(content)
            response = (
                upload(http, uuid4(), content)
                if operation == "post"
                else save(http, item.document_id, content, 1)
            )
            error(response, 422, exc.value.code)
            assert "SYNTHETIC_PRIVATE" not in response.text
    assert api().get_docx(world["runtimes"]["own"], document_id=item.document_id) == item


def test_openapi_and_no_runtime_keep_boundaries(run_world):
    from ara.app import create_app

    app = create_app(document_runtime=run_world["runtimes"]["own"])
    schema = app.openapi()
    assert schema == app.openapi()
    for path, operation, field in (
        ("/docx-documents/{document_id}/import", "post", "title"),
        ("/docx-documents/{document_id}/content", "put", "expected_storage_revision"),
    ):
        definition = schema["paths"][path][operation]
        assert {"200", "404", "409", "413", "415", "422", "500", "503"} <= set(
            definition["responses"]
        )
        body = definition["requestBody"]
        assert body["required"] is True
        for mime in (MIME, "application/octet-stream"):
            assert body["content"][mime]["schema"] == {"type": "string", "format": "binary"}
        parameter = next(p for p in definition["parameters"] if p["name"] == field)
        assert parameter["required"] is True
        if operation == "put":
            maximum = parameter["schema"]["maximum"]
            assert type(maximum) is int and maximum == MAX - 1
    without = create_app().openapi()["paths"]
    assert not any(p.startswith("/docx-documents") for p in without)


async def asgi_request(app, *, headers, chunks):
    """Observe receive consumption; no TestClient buffering of generator bodies."""
    messages, received = [], []
    pending = iter(chunks)

    async def receive():
        message = next(pending, None)
        if message is None:
            await asyncio.Event().wait()
        received.append(message)
        return message

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "root_path": "",
        "path": target(uuid4(), "post"),
        "query_string": b"title=Synthetic",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("localhost", 80),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=5)
    return messages, received


@pytest.mark.parametrize(
    "kind",
    [
        "declared",
        "streamed",
        "disconnect",
        "duplicate-type",
        "duplicate-length",
        "duplicate-encoding",
    ],
)
def test_raw_asgi_bounds_reject_before_storage(run_world, monkeypatch, kind):
    from ara.app import create_app

    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected stream reached storage")

    monkeypatch.setattr(api(), "import_docx", forbidden)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    headers = [(b"content-type", MIME.encode())]
    expected_reads, status, code = 0, 413, "upload_too_large"
    chunks = [{"type": "http.request", "body": b"unused", "more_body": False}]
    if kind == "declared":
        headers.append((b"content-length", str(SIZE + 1).encode()))
    elif kind == "streamed":
        expected_reads = 2
        chunks = [
            {"type": "http.request", "body": b"x" * SIZE, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": True},
            {"type": "http.request", "body": b"must not read", "more_body": False},
        ]
    elif kind == "disconnect":
        expected_reads, status, code = 1, 422, "validation_error"
        chunks = [{"type": "http.disconnect"}]
    else:
        status, code = 422, "validation_error"
        if kind == "duplicate-type":
            headers.append((b"content-type", MIME.encode()))
        elif kind == "duplicate-length":
            headers.extend([(b"content-length", b"1"), (b"content-length", b"1")])
        else:
            headers.extend([(b"content-encoding", b"identity"), (b"content-encoding", b"identity")])
    messages, received = asyncio.run(asgi_request(app, headers=headers, chunks=chunks))
    assert len(received) == expected_reads
    assert next(m["status"] for m in messages if m["type"] == "http.response.start") == status
    import json

    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    assert json.loads(body)["code"] == code


def test_octet_stream_identity_leading_zero_and_threadpool(run_world, monkeypatch):
    service = api()
    actual = service.import_docx
    calls = []

    def guarded(runtime, **kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        calls.append(kwargs["data"])
        return actual(runtime, **kwargs)

    monkeypatch.setattr(service, "import_docx", guarded)
    identity, data = uuid4(), raw()
    with client(run_world["runtimes"]["own"]) as http:
        response = http.post(
            target(identity.hex, "post"),
            params={"title": "Exact"},
            content=data,
            headers={"Content-Type": "APPLICATION/OCTET-STREAM", "Content-Encoding": "IDENTITY"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["document_id"] == str(identity)
        assert calls == [data]
        response = save(http, identity, data, "0001")
        assert response.status_code == 200
        assert response.json()["storage_revision"] == 2


@pytest.mark.parametrize("failure", ["package", "projection", "storage"])
def test_safe_error_classes_are_preserved(run_world, monkeypatch, failure):
    from ara.documents.storage import DocumentError
    from ara.docx_package import DocxError
    from ara.docx_package.projection import ProjectionError

    exceptions = {
        "package": DocxError("unsupported_package"),
        "projection": ProjectionError("projection_limit_exceeded"),
        "storage": DocumentError(
            503, "storage_unavailable", "Document storage is unavailable", True
        ),
    }

    def rejected(*args, **kwargs):
        raise exceptions[failure]

    monkeypatch.setattr(api(), "import_docx", rejected)
    with client(run_world["runtimes"]["own"]) as http:
        response = upload(http, uuid4(), raw())
        error(response, 503 if failure == "storage" else 422, exceptions[failure].code)


def test_final_bigint_save_and_put_runs_off_event_loop(run_world, monkeypatch):
    world = run_world
    item = api().import_docx(
        world["runtimes"]["own"], document_id=uuid4(), title="Synthetic", data=raw()
    )
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE docx_documents SET storage_revision=:rev WHERE id=:id"),
            {"rev": MAX - 1, "id": item.document_id},
        )
    actual = api().save_docx

    def guarded(runtime, **kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return actual(runtime, **kwargs)

    monkeypatch.setattr(api(), "save_docx", guarded)
    with client(world["runtimes"]["own"]) as http:
        response = save(http, item.document_id, raw("last"), MAX - 1)
        assert response.status_code == 200, response.text
        assert response.json()["storage_revision"] == MAX
