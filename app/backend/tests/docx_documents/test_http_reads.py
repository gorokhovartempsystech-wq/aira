"""Transport edge cases independent of database fixture setup."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
from ara.docx_documents import StoredDocx


@pytest.fixture
def transport(monkeypatch):
    import ara.docx_documents as service

    monkeypatch.delenv("ARA_ENVIRONMENT", raising=False)
    engine = create_engine("postgresql+psycopg://")
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    now = datetime.now(timezone.utc)
    snapshot = StoredDocx(
        document_id=uuid4(),
        title='Quotes " and Unicode Я🧪',
        original_data=b"original",
        original_sha256="a" * 64,
        current_data=b"current",
        current_sha256="b" * 64,
        storage_revision=9223372036854775807,
        created_at=now,
        updated_at=now,
    )
    calls = []

    def read(actual_runtime, *, document_id):
        assert actual_runtime is runtime
        assert document_id == snapshot.document_id
        calls.append(document_id)
        return snapshot

    monkeypatch.setattr(service, "get_docx", read)
    app = create_app(document_runtime=runtime)
    try:
        with TestClient(app) as http:
            yield http, app, snapshot, calls
    finally:
        engine.dispose()


def test_last_bigint_revision_and_one_snapshot_per_download(transport):
    http, app, snapshot, calls = transport
    response = http.get(f"/docx-documents/{snapshot.document_id}/content")
    assert response.status_code == 200
    assert response.content == snapshot.current_data
    assert response.headers["x-ara-storage-revision"] == "9223372036854775807"
    assert response.headers["etag"] == f'"{snapshot.current_sha256}"'
    assert calls == [snapshot.document_id]
    assert snapshot.title not in response.headers["content-disposition"]
    assert "original" not in response.text
    assert (
        app.openapi()["components"]["schemas"]["DocxMetadata"]["properties"]["storage_revision"][
            "maximum"
        ]
        == 9223372036854775807
    )
    assert (
        type(
            app.openapi()["components"]["schemas"]["DocxMetadata"]["properties"][
                "current_size_bytes"
            ]["maximum"]
        )
        is int
    )


@pytest.mark.parametrize("suffix", ["", "/content"])
def test_query_rejected_before_snapshot_and_no_download_headers(transport, suffix):
    http, app, snapshot, calls = transport
    response = http.get(f"/docx-documents/{snapshot.document_id}{suffix}?owner_id=forged")
    assert response.status_code == 422
    assert calls == []
    assert "etag" not in response.headers
    assert "x-ara-storage-revision" not in response.headers
    assert "content-disposition" not in response.headers
