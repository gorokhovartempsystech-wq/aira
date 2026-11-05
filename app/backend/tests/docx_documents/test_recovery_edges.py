"""Additional checks of JSONB input and off-loop working copy operations."""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from ara.app import create_app
from ara.docx_documents import import_docx
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.docx_projection_fixtures import package, paragraph
from tests.docx_documents.test_storage_edges import runtime as runtime


def prepare(runtime):
    item = import_docx(
        runtime, document_id=uuid4(), title="Synthetic", data=package(paragraph("Original"))[0]
    )
    http = TestClient(create_app(document_runtime=runtime))
    view = http.get(f"/docx-documents/{item.document_id}/view").json()
    span = view["blocks"][0]["spans"][0]
    data = {
        "expected_token": None,
        "token": str(uuid4()),
        "operation_id": None,
        "edit": {
            "anchor": span["anchor"],
            "expected_storage_revision": "1",
            "expected_text": span["text"],
            "replacement_text": "Changed",
        },
    }
    return http, f"/docx-documents/{item.document_id}/draft", data


@pytest.mark.parametrize("invalid", ["NUL\x00text", "surrogate\ud800"])
def test_unrepresentable_jsonb_text_can_be_corrected(runtime, invalid):
    http, path, data = prepare(runtime)
    with http:
        data["edit"]["replacement_text"] = invalid
        # ASCII JSON escapes are intentional: even a valid UTF8 body must not
        # let an unpaired escaped surrogate reach PostgreSQL's JSONB decoder.
        import json

        response = http.put(
            path, content=json.dumps(data).encode(), headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422 and response.json()["code"] == "validation_error"
        assert http.get(path).json()["draft"] is None
        data["edit"]["replacement_text"] = "Corrected"
        assert http.put(path, json=data).status_code == 200


def test_working_copy_database_io_is_off_event_loop(runtime):
    http, path, data = prepare(runtime)
    calls = []

    def guarded(connection, cursor, statement, parameters, context, executemany):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        calls.append(statement)

    event.listen(runtime.engine, "before_cursor_execute", guarded)
    try:
        with http:
            assert http.put(path, json=data).status_code == 200
            assert http.get(path).json()["draft"]["token"] == data["token"]
            assert (
                http.request("DELETE", path, json={"expected_token": data["token"]}).status_code
                == 204
            )
        assert calls
    finally:
        event.remove(runtime.engine, "before_cursor_execute", guarded)
