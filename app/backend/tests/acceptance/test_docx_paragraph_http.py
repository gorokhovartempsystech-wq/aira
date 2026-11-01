"""Frozen D03-13 acceptance: scoped, durable and atomic paragraph commands."""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from ara.app import create_app
from ara.docx_documents import get_docx, import_docx, save_docx
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.projection import project_docx

ROUTE = "/docx-documents/{document_id}/paragraph-commands"


def seed(world):
    return import_docx(
        world["runtimes"]["own"],
        document_id=uuid4(),
        title="Synthetic requirements",
        data=create_docx(tuple(NewParagraph(f"Device {i} 😀") for i in range(4))),
    )


def path(item):
    return ROUTE.format(document_id=item.document_id)


def headers(key):
    return {"Idempotency-Key": str(key)}


def command(item, index=0, kind="insert", **kwargs):
    p = project_docx(item.current_data).blocks[index]
    anchor = asdict(p.anchor)
    anchor["path"] = list(anchor["path"])
    return {"kind": kind, "anchor": anchor, "expected_text": p.text, **kwargs}


def body(item, kind="structure", commands=None):
    return {
        "expected_storage_revision": str(item.storage_revision),
        "kind": kind,
        "commands": commands
        if commands is not None
        else [command(item, texts=["Added paragraph"])],
    }


def rows(world):
    with world["engine"].connect() as conn:
        return conn.execute(text("SELECT * FROM docx_edit_receipts")).mappings().all()


def error(response, status, code):
    assert response.status_code == status, response.text
    data = response.json()
    assert set(data) == {"code", "message", "request_id", "retryable"}
    assert data["code"] == code
    assert "SYNTHETIC_PRIVATE" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_structure_format_save_and_download_preserve_original(run_world):
    item = seed(run_world)
    with run_world["client"]() as http:
        request = body(
            item,
            commands=[command(item, texts=["New heading", "New item"]), command(item, 3, "delete")],
        )
        saved = http.post(path(item), json=request, headers=headers(uuid4()))
        assert saved.status_code == 200, saved.text
        assert saved.json()["storage_revision"] == "2"
        current = get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
        assert [p.text for p in project_docx(current.current_data).blocks] == [
            "Device 0 😀",
            "New heading",
            "New item",
            "Device 1 😀",
            "Device 2 😀",
        ]
        key = uuid4()
        request = body(
            current,
            "format",
            [
                command(current, 1, "format", style_id="Heading1"),
                command(current, 2, "format", style_id="ListNumber", list_kind="numbered"),
            ],
        )
        saved = http.post(path(item), json=request, headers=headers(key))
        assert saved.status_code == 200, saved.text
        assert saved.json()["operation_id"] == str(key)
        assert saved.json()["storage_revision"] == "3"
        download = http.get(f"/docx-documents/{item.document_id}/content")
        assert download.status_code == 200
        blocks = project_docx(download.content).blocks
        assert blocks[1].style_id == "Heading1" and blocks[2].numbering_id is not None
        assert download.headers["x-ara-storage-revision"] == "3"
    latest = get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
    assert latest.original_data == item.original_data
    with (
        ZipFile(io.BytesIO(item.original_data)) as old,
        ZipFile(io.BytesIO(latest.current_data)) as new,
    ):
        assert all(
            old.read(n) == new.read(n)
            for n in old.namelist()
            if n not in ("word/document.xml", "word/numbering.xml")
        )
    assert len(rows(run_world)) == 2


def test_durable_replay_after_newer_save_and_changed_payload_conflict(run_world):
    item, key = seed(run_world), uuid4()
    request = body(item)
    with run_world["client"]() as http:
        first = http.post(path(item), json=request, headers=headers(key))
        assert first.status_code == 200, first.text
    later = save_docx(
        run_world["runtimes"]["own"],
        document_id=item.document_id,
        expected_storage_revision=2,
        data=create_docx((NewParagraph("Later content"),)),
    )
    with run_world["client"]() as reopened:
        replay = reopened.post(
            path(item),
            content=json.dumps(request, indent=3),
            headers={**headers(key), "Content-Type": "application/json"},
        )
        assert replay.status_code == 200 and replay.json() == first.json()
        changed = deepcopy(request)
        changed["commands"][0]["texts"] = ["Different"]
        error(
            reopened.post(path(item), json=changed, headers=headers(key)),
            409,
            "idempotency_conflict",
        )
    assert get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == later
    assert len(rows(run_world)) == 1


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_keys_share_docx_lock(run_world, same_key):
    item, key = seed(run_world), uuid4()
    request = body(item)

    def submit(attempt):
        with run_world["client"]() as http:
            return http.post(path(item), json=request, headers=headers(attempt))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, [key, key if same_key else uuid4()]))
    assert sorted(r.status_code for r in results) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert results[0].json() == results[1].json()
    assert len(rows(run_world)) == 1
    assert (
        get_docx(run_world["runtimes"]["own"], document_id=item.document_id).storage_revision == 2
    )


@pytest.mark.parametrize("after_commit", [False, True])
def test_commit_fault_retries_without_losing_or_duplicating_paragraph(
    run_world, monkeypatch, after_commit
):
    item, key = seed(run_world), uuid4()
    request = body(item)
    real = run_world["engine"].dialect.do_commit

    def fail(connection):
        if after_commit:
            real(connection)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(run_world["engine"].dialect, "do_commit", fail)
        with run_world["client"]() as http:
            error(
                http.post(path(item), json=request, headers=headers(key)),
                503,
                "storage_unavailable",
            )
    saved = get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
    assert saved.storage_revision == (2 if after_commit else 1)
    assert len(rows(run_world)) == int(after_commit)
    with run_world["client"]() as http:
        result = http.post(path(item), json=request, headers=headers(key))
        assert result.status_code == 200 and result.json()["storage_revision"] == "2"
        assert http.post(path(item), json=request, headers=headers(key)).json() == result.json()
    assert len(rows(run_world)) == 1


def test_receipt_insert_failure_rolls_back_package(run_world):
    item = seed(run_world)

    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO DOCX_EDIT_RECEIPTS"):
            raise RuntimeError("SYNTHETIC_PRIVATE")

    event.listen(run_world["engine"], "before_cursor_execute", fail)
    try:
        with run_world["client"]() as http:
            error(
                http.post(path(item), json=body(item), headers=headers(uuid4())),
                500,
                "storage_error",
            )
    finally:
        event.remove(run_world["engine"], "before_cursor_execute", fail)
    assert rows(run_world) == []
    assert get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == item


@pytest.mark.parametrize(
    "fault,code,status",
    [
        ("revision", "docx_conflict", 409),
        ("source", "stale_source", 409),
        ("text", "text_mismatch", 409),
        ("anchor", "invalid_anchor", 422),
        ("duplicate", "conflicting_commands", 422),
        ("style", "unsupported_format", 422),
    ],
)
def test_whole_batch_rejection_keeps_bytes_revision_and_receipts(run_world, fault, code, status):
    item = seed(run_world)
    request = body(item)
    value = request["commands"][0]
    if fault == "revision":
        request["expected_storage_revision"] = "2"
    elif fault == "source":
        value["anchor"]["source_sha256"] = "0" * 64
    elif fault == "text":
        value["expected_text"] = "SYNTHETIC_PRIVATE"
    elif fault == "anchor":
        value["anchor"]["path"] = [10000]
    elif fault == "duplicate":
        request["commands"].append(deepcopy(value))
    else:
        request = body(item, "format", [command(item, kind="format", style_id="Missing")])
    with run_world["client"]() as http:
        error(http.post(path(item), json=request, headers=headers(uuid4())), status, code)
    assert rows(run_world) == []
    assert get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == item


def test_scope_before_replay_and_cross_endpoint_ledger_conflict(run_world):
    item, key = seed(run_world), uuid4()
    request = body(item)
    with run_world["client"]() as http:
        first = http.post(path(item), json=request, headers=headers(key))
        assert first.status_code == 200, first.text
        current = get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
        p = project_docx(current.current_data).blocks[0]
        span = p.spans[0]
        anchor = asdict(span.anchor)
        anchor["path"] = list(anchor["path"])
        edit = {
            "expected_storage_revision": "2",
            "anchor": anchor,
            "expected_text": span.text,
            "replacement_text": "Edited",
        }
        error(
            http.post(
                f"/docx-documents/{item.document_id}/text-edit", json=edit, headers=headers(key)
            ),
            409,
            "idempotency_conflict",
        )
        error(
            http.post(
                path(item),
                json=body(current, "format", [command(current, kind="format")]),
                headers=headers(key),
            ),
            409,
            "idempotency_conflict",
        )
    for scope in ("peer", "foreign"):
        with run_world["client"](scope) as http:
            error(http.post(path(item), json=request, headers=headers(key)), 404, "not_found")
    assert len(rows(run_world)) == 1


@pytest.mark.parametrize("corruption", ["current", "receipt"])
def test_corruption_is_never_replayed_as_success(run_world, corruption):
    item, key = seed(run_world), uuid4()
    request = body(item)
    with run_world["client"]() as http:
        assert http.post(path(item), json=request, headers=headers(key)).status_code == 200
        with run_world["engine"].begin() as conn:
            conn.execute(
                text(
                    "UPDATE docx_documents SET current_sha256=:h WHERE id=:id"
                    if corruption == "current"
                    else "UPDATE docx_edit_receipts SET current_sha256=:h WHERE document_id=:id"
                ),
                {"h": "0" * 64, "id": item.document_id},
            )
        error(http.post(path(item), json=request, headers=headers(key)), 500, "storage_error")


def test_noop_counts_once_and_worker_thread_performs_storage(run_world):
    import threading

    item, key = seed(run_world), uuid4()
    request = body(item, "format", [command(item, kind="format", style_id="Normal")])
    names = []

    def note(*args):
        names.append(threading.current_thread().name)

    event.listen(run_world["engine"], "before_cursor_execute", note)
    try:
        with run_world["client"]() as http:
            result = http.post(path(item), json=request, headers=headers(key))
            assert result.status_code == 200 and result.json()["storage_revision"] == "2"
            assert http.post(path(item), json=request, headers=headers(key)).json() == result.json()
    finally:
        event.remove(run_world["engine"], "before_cursor_execute", note)
    assert names and all("AnyIO worker thread" in n for n in names)
    assert (
        get_docx(run_world["runtimes"]["own"], document_id=item.document_id).current_data
        == item.current_data
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_key",
        "duplicate_key",
        "query",
        "invalid_key",
        "bad_json",
        "duplicate_json",
        "utf8",
        "nan",
        "media",
        "encoding",
        "unknown_field",
        "empty",
        "mixed",
        "revision",
        "bool_path",
        "bad_text",
    ],
)
def test_invalid_transport_and_dto_never_reach_storage(isolated_client, fault):
    # isolated_client connects/disposes fail on access. Valid envelope is synthetic.
    data = create_docx((NewParagraph("SYNTHETIC_PRIVATE"),))

    class Item:
        current_data = data
        storage_revision = 1

    request = body(Item())
    values = {**headers(uuid4()), "Content-Type": "application/json"}
    target = ROUTE.format(document_id=uuid4())
    status, code = 422, "validation_error"
    if fault == "missing_key":
        values.pop("Idempotency-Key")
    elif fault == "duplicate_key":
        values = list(values.items()) + [("Idempotency-Key", str(uuid4()))]
    elif fault == "query":
        target += "?unexpected=1"
    elif fault == "invalid_key":
        values["Idempotency-Key"] = "BAD"
    elif fault == "media":
        values["Content-Type"] = "text/plain"
        status, code = 415, "unsupported_media_type"
    elif fault == "encoding":
        values["Content-Encoding"] = "gzip"
        status, code = 415, "unsupported_media_type"
    elif fault == "unknown_field":
        request["SYNTHETIC_PRIVATE"] = True
    elif fault == "empty":
        request["commands"] = []
    elif fault == "mixed":
        request["kind"] = "format"
    elif fault == "revision":
        request["expected_storage_revision"] = "01"
    elif fault == "bool_path":
        request["commands"][0]["anchor"]["path"] = [True]
    elif fault == "bad_text":
        request["commands"][0]["texts"] = ["bad\u0000"]
    encoded = json.dumps(request).encode()
    if fault == "bad_json":
        encoded = b"{"
    elif fault == "duplicate_json":
        encoded = b'{"kind":"structure","kind":"format"}'
    elif fault == "utf8":
        encoded = b'"\xff"'
    elif fault == "nan":
        encoded = b'{"value":NaN}'
    error(isolated_client.post(target, content=encoded, headers=values), status, code)


def test_default_factory_and_openapi_are_inert_and_truthful(isolated_client):
    with TestClient(create_app()) as http:
        assert set(http.get("/openapi.json").json()["paths"]) == {"/health"}
    schema = isolated_client.get("/openapi.json").json()
    route = schema["paths"][ROUTE]["post"]
    assert {"200", "404", "409", "413", "415", "422", "500", "503"} <= set(route["responses"])
    header = next(p for p in route["parameters"] if p["name"] == "Idempotency-Key")
    assert header["required"] is True and header["in"] == "header"
    assert route["requestBody"]["required"] is True
    assert route["requestBody"]["content"]["application/json"]["schema"]


@pytest.fixture
def isolated_client(monkeypatch):
    from sqlalchemy import create_engine

    from ara.documents.runtime import DocumentRuntime

    engine = create_engine("postgresql+psycopg://synthetic@localhost/unused")

    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected storage access")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(engine, "connect", forbidden)
            patch.setattr(engine, "dispose", forbidden)
            runtime = DocumentRuntime(
                engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local"
            )
            with TestClient(
                create_app(document_runtime=runtime), raise_server_exceptions=False
            ) as http:
                yield http
    finally:
        engine.dispose()
