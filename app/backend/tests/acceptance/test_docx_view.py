"""Frozen D03-02 view acceptance: source fidelity, isolation and bounded JSON."""

from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from docx_projection_fixtures import package, paragraph
from docx_storage_fixtures import api, raw
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool
from test_docx_http_reads import MAX, client, error

FIELDS = {
    "document_id",
    "title",
    "storage_revision",
    "current_sha256",
    "current_size_bytes",
    "created_at",
    "updated_at",
    "body_anchor",
    "coverage_scope",
    "has_unprojected_content",
    "blocks",
    "notices",
}


def seed(world, data=None, scope="own"):
    return api().import_docx(
        world["runtimes"][scope],
        document_id=uuid4(),
        title="Synthetic view",
        data=raw() if data is None else data,
    )


def path(item):
    return f"/docx-documents/{item.document_id}/view"


def json_domain(value):
    import json

    return json.loads(json.dumps(value))


def test_rich_projection_exact_anchors_no_writes_and_download_unchanged(run_world):
    from ara.docx_package.projection import project_docx

    world = run_world
    source = Path("tests/fixtures/docx/rich-source.docx").read_bytes()
    item = seed(world, source)
    native = project_docx(source)
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    event.listen(world["engine"], "before_cursor_execute", observe)
    try:
        with client(world["runtimes"]["own"]) as http:
            response = http.get(path(item))
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            view = response.json()
            assert set(view) == FIELDS
            assert view["document_id"] == str(item.document_id)
            assert view["storage_revision"] == "1"
            assert view["current_sha256"] == sha256(source).hexdigest()
            assert view["current_size_bytes"] == len(source)
            assert view["blocks"] == json_domain([asdict(b) for b in native.blocks])
            assert view["notices"] == json_domain([asdict(n) for n in native.notices])
            assert view["body_anchor"] == json_domain(asdict(native.body_anchor))
            assert view["coverage_scope"] == native.coverage_scope
            assert view["has_unprojected_content"] is native.has_unprojected_content
            assert http.get(f"/docx-documents/{item.document_id}/content").content == source
    finally:
        event.remove(world["engine"], "before_cursor_execute", observe)
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "MERGE")) for s in statements)
    # Resolve every text anchor independently against the original XML.
    with ZipFile(BytesIO(source)) as archive:
        root = ET.fromstring(archive.read(native.source.main_part))
    pending = list(view["blocks"])
    checked = 0
    while pending:
        block = pending.pop()
        if block["kind"] == "table":
            pending.extend(b for r in block["rows"] for c in r["cells"] for b in c["blocks"])
        elif block["kind"] == "paragraph":
            for span in block["spans"]:
                if span["kind"] == "text":
                    node = root
                    for index in span["anchor"]["path"]:
                        node = list(node)[index]
                    assert node.text or span["text"] == ""
                    assert (node.text or "") == span["text"]
                    assert span["end"] - span["start"] == len(span["text"])
                    checked += 1
    assert checked > 10
    assert api().get_docx(world["runtimes"]["own"], document_id=item.document_id) == item


def test_unicode_nested_tables_and_opaque_are_not_silently_lost(run_world):
    from ara.docx_package.projection import project_docx

    body = (
        paragraph("<img onerror=alert(1)> Я🧪 e\u0301\t")
        + '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
        + paragraph("Cell")
        + "<w:tbl><w:tr><w:tc>"
        + paragraph("Nested")
        + "</w:tc></w:tr></w:tbl></w:tc></w:tr></w:tbl>"
        + "<w:sdt><w:sdtContent>"
        + paragraph("Opaque text")
        + "</w:sdtContent></w:sdt>"
    )
    source = package(body)[0]
    item = seed(run_world, source)
    native = project_docx(source)
    with client(run_world["runtimes"]["own"]) as http:
        response = http.get(path(item))
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["blocks"] == json_domain([asdict(b) for b in native.blocks])
        assert view["has_unprojected_content"] is True
        assert view["blocks"][0]["text"].startswith("<img onerror=alert(1)> Я🧪")


def test_latest_saved_snapshot_max_revision_and_new_engine(run_world):
    world = run_world
    item = seed(world)
    changed = api().save_docx(
        world["runtimes"]["own"],
        document_id=item.document_id,
        expected_storage_revision=1,
        data=raw("Latest 🧪"),
    )
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE docx_documents SET storage_revision=:rev WHERE id=:id"),
            {"rev": MAX, "id": item.document_id},
        )
    engine = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with client(replace(world["runtimes"]["own"], engine=engine)) as http:
            view = http.get(path(item)).json()
            assert view["storage_revision"] == str(MAX)
            assert view["current_sha256"] == changed.current_sha256
            assert view["blocks"][0]["text"] == "Latest 🧪"
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_scoped_not_found_and_safe_errors(run_world, scope):
    foreign = seed(run_world, scope=scope)
    with client(run_world["runtimes"]["own"]) as http:
        hidden = error(http.get(path(foreign)), 404, "not_found")
        missing = error(http.get(f"/docx-documents/{uuid4()}/view"), 404, "not_found")
        assert hidden["message"] == missing["message"]


@pytest.mark.parametrize("query", ["unknown=private", "offset=0", "a=1&a=2"])
def test_bad_query_rejected_before_storage(run_world, monkeypatch, query):
    def forbidden(*args, **kwargs):
        raise AssertionError("Query must not reach storage")

    monkeypatch.setattr(api(), "get_docx", forbidden)
    with client(run_world["runtimes"]["own"]) as http:
        error(http.get(f"/docx-documents/{uuid4()}/view?{query}"), 422, "validation_error")
        error(http.get("/docx-documents/invalid/view"), 422, "validation_error")


@pytest.mark.parametrize("failure", ["corrupt", "unavailable", "unexpected"])
def test_storage_and_build_errors_never_expose_content(run_world, monkeypatch, failure):
    from ara.documents.storage import DocumentError

    item = seed(run_world)
    if failure == "corrupt":
        with run_world["engine"].begin() as connection:
            connection.execute(
                text("UPDATE docx_documents SET current_data=:data WHERE id=:id"),
                {"data": b"SYNTHETIC_PRIVATE_corrupt", "id": item.document_id},
            )
    else:

        def broken(*args, **kwargs):
            if failure == "unavailable":
                raise DocumentError(
                    503, "storage_unavailable", "Document storage is unavailable", True
                )
            raise ValueError("SYNTHETIC_PRIVATE_unexpected")

        monkeypatch.setattr(api(), "get_docx", broken)
    with client(run_world["runtimes"]["own"]) as http:
        response = http.get(path(item))
        error(
            response,
            503 if failure == "unavailable" else 500,
            "storage_unavailable" if failure == "unavailable" else "storage_error",
        )
        assert "SYNTHETIC_PRIVATE" not in response.text


@pytest.mark.parametrize("kind", ["text", "records"])
def test_view_budget_is_explicit_and_does_not_prevent_download(run_world, kind):
    source = raw("x" * 500001) if kind == "text" else package(paragraph("x") * 1300)[0]
    item = seed(run_world, source)
    with client(run_world["runtimes"]["own"]) as http:
        response = http.get(path(item))
        payload = error(response, 413, "view_limit_exceeded")
        assert payload["message"] == "DOCX view exceeds a technical limit"
        assert "blocks" not in payload
        assert http.get(f"/docx-documents/{item.document_id}/content").content == source


def test_view_openapi_and_default_factory(run_world):
    from ara.app import create_app

    with client(run_world["runtimes"]["own"]) as http:
        schema = http.get("/openapi.json").json()
        route = schema["paths"]["/docx-documents/{document_id}/view"]
        assert set(route) == {"get"}
        assert {"200", "404", "413", "422", "500", "503"} <= set(route["get"]["responses"])
        reference = route["get"]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        model = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]
        assert set(model["properties"]) == FIELDS
        assert model["properties"]["storage_revision"]["type"] == "string"
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as http:
        assert http.get(f"/docx-documents/{uuid4()}/view").status_code == 404
