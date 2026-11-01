"""Frozen D03-03 acceptance for anchored manual edits with final storage CAS."""

import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest
from docx_projection_fixtures import package, paragraph
from docx_storage_fixtures import api, raw
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from test_docx_http_reads import FIELDS, MAX, client, error


def seed(world, source=None, scope="own"):
    return api().import_docx(
        world["runtimes"][scope],
        document_id=uuid4(),
        title="Synthetic edit",
        data=raw("Device 🧪") if source is None else source,
    )


def path(item):
    return f"/docx-documents/{item.document_id}/text-edit"


def spans(blocks):
    result = []
    for block in blocks:
        if block["kind"] == "paragraph":
            result.extend(s for s in block["spans"] if s["kind"] == "text")
        elif block["kind"] == "table":
            result.extend(s for r in block["rows"] for c in r["cells"] for s in spans(c["blocks"]))
    return result


def body(http, item, replacement="Updated Я🧪", *, target=None):
    view = http.get(f"/docx-documents/{item.document_id}/view").json()
    span = next(s for s in spans(view["blocks"]) if target is None or s["text"] == target)
    return {
        "expected_storage_revision": view["storage_revision"],
        "anchor": span["anchor"],
        "expected_text": span["text"],
        "replacement_text": replacement,
    }


def test_rich_edit_preserves_original_parts_and_survives_reopen(run_world):
    world = run_world
    source = Path("tests/fixtures/docx/rich-source.docx").read_bytes()
    item = seed(world, source)
    with client(world["runtimes"]["own"]) as http:
        request = body(http, item, "Kitchen heating", target="Kitchen warmth")
        response = http.post(path(item), json=request)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert set(receipt) == FIELDS and receipt["storage_revision"] == "2"
        assert response.headers["cache-control"] == "no-store"
        saved = api().get_docx(world["runtimes"]["own"], document_id=item.document_id)
        assert saved.original_data == source and saved.current_data != source
        assert receipt["current_sha256"] == saved.current_sha256
        with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(saved.current_data)) as after:
            untouched = [name for name in before.namelist() if name != "word/document.xml"]
            assert len(untouched) == 19
            assert all(before.read(name) == after.read(name) for name in untouched)
        view = http.get(f"/docx-documents/{item.document_id}/view").json()
        texts = [s["text"] for s in spans(view["blocks"])]
        assert "Kitchen heating" in texts and "Kitchen warmth" not in texts
        error(http.post(path(item), json=request), 409, "docx_conflict")
    engine = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with client(replace(world["runtimes"]["own"], engine=engine)) as reopened:
            assert (
                reopened.get(f"/docx-documents/{item.document_id}/content").content
                == saved.current_data
            )
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "fault,code,status",
    [
        ("revision", "docx_conflict", 409),
        ("source", "stale_source", 409),
        ("expected", "text_mismatch", 409),
        ("anchor", "invalid_anchor", 422),
        ("newline", "unsupported_edit", 422),
        ("nul", "invalid_input", 422),
    ],
)
def test_rejected_edit_preserves_every_stored_field(run_world, fault, code, status):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        if fault == "revision":
            request["expected_storage_revision"] = "2"
        if fault == "source":
            request["anchor"]["source_sha256"] = "0" * 64
        if fault == "expected":
            request["expected_text"] = "SYNTHETIC_PRIVATE_wrong"
        if fault == "anchor":
            request["anchor"]["path"] = [100000]
        if fault == "newline":
            request["replacement_text"] = "new\nparagraph"
        if fault == "nul":
            request["replacement_text"] = "bad\x00text"
        response = http.post(path(item), json=request)
        error(response, status, code)
        assert "SYNTHETIC_PRIVATE" not in response.text
    assert api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == item


@pytest.mark.parametrize(
    "change",
    [
        {"expected_storage_revision": 1},
        {"expected_storage_revision": True},
        {"expected_storage_revision": "01"},
        {"expected_storage_revision": "0"},
        {"expected_storage_revision": str(MAX)},
        {"expected_storage_revision": "1e0"},
        {"expected_storage_revision": "١"},
        {"expected_storage_revision": "0" * 20},
        {"extra": "forged"},
        {"expected_text": None},
        {"replacement_text": False},
        {"replacement_text": "x" * 100001},
    ],
)
def test_strict_request_types_and_limits_before_storage(run_world, monkeypatch, change):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
    request.update(change)

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input reached storage")

    monkeypatch.setattr(api(), "get_docx", forbidden)
    with client(run_world["runtimes"]["own"]) as http:
        error(http.post(path(item), json=request), 422, "validation_error")


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "A" * 64},
        {"part_name": ""},
        {"path": [True]},
        {"path": [-1]},
        {"path": [100001]},
        {"path": []},
        {"path": [0] * 129},
        {"path": "0"},
        {"extra": 1},
    ],
)
def test_anchor_shape_is_strict(run_world, change):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        request["anchor"].update(change)
        error(http.post(path(item), json=request), 422, "validation_error")


@pytest.mark.parametrize(
    "content",
    [
        b'{"replacement_text":"one","replacement_text":"two"}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b"null",
        b"[]",
        b'{"a":"\xff"}',
        b"{broken",
    ],
)
def test_bad_json_is_safe(run_world, content):
    with client(run_world["runtimes"]["own"]) as http:
        error(
            http.post(
                f"/docx-documents/{uuid4()}/text-edit",
                content=content,
                headers={"Content-Type": "application/json"},
            ),
            422,
            "validation_error",
        )


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_scope_cannot_be_forged(run_world, scope):
    item = seed(run_world, scope=scope)
    with client(run_world["runtimes"][scope]) as owner:
        request = body(owner, item)
    with client(run_world["runtimes"]["own"]) as http:
        error(http.post(path(item), json=request), 404, "not_found")
    assert api().get_docx(run_world["runtimes"][scope], document_id=item.document_id) == item


def test_concurrent_writer_between_export_and_final_save_wins(run_world, monkeypatch):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
    actual = api().save_docx
    winner = raw("Other writer")

    def racing(runtime, **kwargs):
        actual(runtime, document_id=item.document_id, expected_storage_revision=1, data=winner)
        return actual(runtime, **kwargs)

    monkeypatch.setattr(api(), "save_docx", racing)
    with client(run_world["runtimes"]["own"]) as http:
        error(http.post(path(item), json=request), 409, "docx_conflict")
    saved = api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
    assert saved.current_data == winner and saved.original_data == item.original_data
    assert saved.storage_revision == 2


def test_unicode_noop_and_last_bigint_revision(run_world):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        request["replacement_text"] = request["expected_text"]
        response = http.post(path(item), json=request)
        assert response.status_code == 200 and response.json()["storage_revision"] == "2"
        assert (
            api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id).current_data
            == item.current_data
        )
        with run_world["engine"].begin() as conn:
            conn.execute(
                text("UPDATE docx_documents SET storage_revision=:r WHERE id=:id"),
                {"r": MAX - 1, "id": item.document_id},
            )
        request = body(http, item, "  e\u0301 Я🧪 <b>literal</b>  ")
        response = http.post(path(item), json=request)
        assert response.status_code == 200, response.text
        assert response.json()["storage_revision"] == str(MAX)
        view = http.get(f"/docx-documents/{item.document_id}/view").json()
        assert spans(view["blocks"])[0]["text"] == request["replacement_text"]


def test_protected_content_rejects_real_changes(run_world):
    settings = b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:documentProtection/></w:settings>'
    source = package(
        paragraph("Protected"),
        extra_parts={"word/settings.xml": settings},
        extra_types={
            "word/settings.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
            )
        },
    )[0]
    item = seed(run_world, source)
    with client(run_world["runtimes"]["own"]) as http:
        error(http.post(path(item), json=body(http, item)), 422, "unsupported_edit")
    assert api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == item


@pytest.mark.parametrize(
    "headers,status,code",
    [
        ({"Content-Type": "application/octet-stream"}, 415, "unsupported_media_type"),
        (
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
            415,
            "unsupported_media_type",
        ),
        (
            {"Content-Type": "application/json", "Content-Length": str(2 * 1024 * 1024 + 1)},
            413,
            "edit_request_too_large",
        ),
        ({"Content-Type": "application/json", "Content-Length": "-1"}, 422, "validation_error"),
    ],
)
def test_transport_rejection(run_world, headers, status, code):
    with client(run_world["runtimes"]["own"]) as http:
        error(
            http.post(f"/docx-documents/{uuid4()}/text-edit", content=b"{}", headers=headers),
            status,
            code,
        )


def test_query_uuid_and_openapi(run_world):
    with client(run_world["runtimes"]["own"]) as http:
        error(
            http.post(
                f"/docx-documents/{uuid4()}/text-edit?a=1",
                content=b"{}",
                headers={"Content-Type": "application/json"},
            ),
            422,
            "validation_error",
        )
        error(http.post("/docx-documents/invalid/text-edit", json={}), 422, "validation_error")
        schema = http.get("/openapi.json").json()
        route = schema["paths"]["/docx-documents/{document_id}/text-edit"]["post"]
        assert {"200", "404", "409", "413", "415", "422", "500", "503"} <= set(route["responses"])
        ref = route["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        request = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        assert request["additionalProperties"] is False
        assert request["properties"]["expected_storage_revision"]["type"] == "string"


@pytest.mark.parametrize("kind", ["declared", "streamed", "disconnect", "duplicate"])
def test_edit_stream_bounds_before_storage(run_world, monkeypatch, kind):
    import asyncio

    from ara.app import create_app

    def forbidden(*args, **kwargs):
        raise AssertionError("Bad stream reached storage")

    monkeypatch.setattr(api(), "get_docx", forbidden)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    headers = [(b"content-type", b"application/json")]
    chunks = [{"type": "http.request", "body": b"{}", "more_body": False}]
    expected_reads, status, code = 0, 413, "edit_request_too_large"
    if kind == "declared":
        headers.append((b"content-length", b"2097153"))
    elif kind == "streamed":
        expected_reads = 2
        chunks = [
            {"type": "http.request", "body": b"x" * 2097152, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": True},
            {"type": "http.request", "body": b"not read", "more_body": False},
        ]
    elif kind == "disconnect":
        expected_reads, status, code = 1, 422, "validation_error"
        chunks = [{"type": "http.disconnect"}]
    else:
        status, code = 422, "validation_error"
        headers.append((b"content-type", b"application/json"))

    async def run():
        received = []
        sent = []
        iterator = iter(chunks)

        async def receive():
            message = next(iterator, None)
            if message is None:
                await asyncio.Event().wait()
            received.append(message)
            return message

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "root_path": "",
            "path": f"/docx-documents/{uuid4()}/text-edit",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1),
            "server": ("localhost", 80),
        }
        await asyncio.wait_for(app(scope, receive, send), 5)
        return received, sent

    received, sent = asyncio.run(run())
    assert len(received) == expected_reads
    assert next(m["status"] for m in sent if m["type"] == "http.response.start") == status
    raw_response = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert json.loads(raw_response)["code"] == code


@pytest.mark.parametrize("kind", ["unavailable", "unexpected"])
def test_safe_storage_errors(run_world, monkeypatch, kind):
    from ara.documents.storage import DocumentError

    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)

    def broken(*args, **kwargs):
        if kind == "unavailable":
            raise DocumentError(503, "storage_unavailable", "Document storage is unavailable", True)
        raise RuntimeError("SYNTHETIC_PRIVATE_failure")

    monkeypatch.setattr(api(), "get_docx", broken)
    with client(run_world["runtimes"]["own"]) as http:
        response = http.post(path(item), json=request)
        error(
            response,
            503 if kind == "unavailable" else 500,
            "storage_unavailable" if kind == "unavailable" else "storage_error",
        )
        assert "SYNTHETIC_PRIVATE" not in response.text


def test_storage_work_is_off_event_loop(run_world, monkeypatch):
    import asyncio

    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
    actual = api().save_docx
    calls = []

    def guarded(runtime, **kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        calls.append(kwargs["data"])
        return actual(runtime, **kwargs)

    monkeypatch.setattr(api(), "save_docx", guarded)
    with client(run_world["runtimes"]["own"]) as http:
        assert http.post(path(item), json=request).status_code == 200
    assert len(calls) == 1
