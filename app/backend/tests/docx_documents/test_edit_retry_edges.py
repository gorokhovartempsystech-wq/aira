"""Additional implementation checks for the keyed edit transaction boundary."""

import asyncio
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from ara.app import create_app
from ara.docx_documents import get_docx, import_docx
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.docx_projection_fixtures import package, paragraph
from tests.docx_documents.test_storage_edges import runtime as runtime


def prepare(runtime, source):
    item = import_docx(runtime, document_id=uuid4(), title="Synthetic retry", data=source)
    http = TestClient(create_app(document_runtime=runtime))
    view = http.get(f"/docx-documents/{item.document_id}/view").json()
    span = view["blocks"][0]["spans"][0]
    request = {
        "expected_storage_revision": view["storage_revision"],
        "anchor": span["anchor"],
        "expected_text": span["text"],
        "replacement_text": "Edited",
    }
    return item, http, request


def test_keyed_edit_cannot_bypass_document_protection(runtime):
    source = package(
        paragraph("Protected"),
        extra_parts={
            "word/settings.xml": (
                b'<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                b"<w:documentProtection/></w:settings>"
            )
        },
        extra_types={
            "word/settings.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
            )
        },
    )[0]
    item, http, request = prepare(runtime, source)
    with http:
        response = http.post(
            f"/docx-documents/{item.document_id}/text-edit",
            json=request,
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422 and response.json()["code"] == "unsupported_edit"
    assert get_docx(runtime, document_id=item.document_id) == item
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0


def test_keyed_write_and_replay_do_not_run_database_on_event_loop(runtime):
    source = package(paragraph("Original"))[0]
    item, http, request = prepare(runtime, source)
    calls = []

    def guarded(connection, cursor, statement, parameters, context, executemany):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            calls.append(statement)
        else:
            raise AssertionError("Blocking database work on event loop")

    event.listen(runtime.engine, "before_cursor_execute", guarded)
    try:
        with http:
            headers = {"Idempotency-Key": str(uuid4())}
            path = f"/docx-documents/{item.document_id}/text-edit"
            response = http.post(path, json=request, headers=headers)
            assert response.status_code == 200
            count = len(calls)
            assert count > 0
            replay = http.post(path, json=request, headers=headers)
            assert replay.status_code == 200 and replay.json() == response.json()
            assert len(calls) > count
    finally:
        event.remove(runtime.engine, "before_cursor_execute", guarded)
