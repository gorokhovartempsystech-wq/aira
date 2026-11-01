"""Frozen D03-04 HTTP acceptance; durable receipts, never text-based inference."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from docx_storage_fixtures import api, raw
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from test_docx_http_reads import MAX, client, error
from test_docx_text_edit import body, path, seed


def headers(key):
    return {"Idempotency-Key": str(key)}


def receipts(world):
    with world["engine"].connect() as conn:
        return (
            conn.execute(text("SELECT * FROM docx_edit_receipts ORDER BY document_id,operation_id"))
            .mappings()
            .all()
        )


def test_replay_is_durable_semantic_and_does_not_rewrite_newer_content(run_world):
    world = run_world
    item, key = seed(world), uuid4()
    with client(world["runtimes"]["own"]) as http:
        request = body(http, item)
        first = http.post(path(item), json=request, headers=headers(key))
        assert first.status_code == 200, first.text
        assert first.json()["storage_revision"] == "2"
        assert first.headers["cache-control"] == "no-store"
    rows = receipts(world)
    assert len(rows) == 1
    assert (
        rows[0]["request_sha256"]
        == sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    latest = api().save_docx(
        world["runtimes"]["own"],
        document_id=item.document_id,
        expected_storage_revision=2,
        data=raw("later writer"),
    )
    engine = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with client(replace(world["runtimes"]["own"], engine=engine)) as reopened:
            response = reopened.post(
                path(item),
                content=json.dumps(
                    dict(reversed(list(request.items()))), ensure_ascii=False, indent=3
                ).encode(),
                headers={**headers(key), "Content-Type": "application/json"},
            )
            assert response.status_code == 200 and response.json() == first.json()
    finally:
        engine.dispose()
    assert api().get_docx(world["runtimes"]["own"], document_id=item.document_id) == latest
    assert receipts(world) == rows


@pytest.mark.parametrize("field", ["replacement_text", "expected_text", "anchor", "revision"])
def test_key_cannot_be_reused_for_another_request(run_world, field):
    item, key = seed(run_world), uuid4()
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        assert http.post(path(item), json=request, headers=headers(key)).status_code == 200
        before = api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
        changed = deepcopy(request)
        if field == "anchor":
            changed["anchor"]["path"] += [0]
        elif field == "revision":
            changed["expected_storage_revision"] = "2"
        else:
            changed[field] += " "
        error(
            http.post(path(item), json=changed, headers=headers(key)), 409, "idempotency_conflict"
        )
    assert len(receipts(run_world)) == 1
    assert api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == before


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_attempts_apply_once(run_world, same_key):
    item, key = seed(run_world), uuid4()
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)

    def submit(attempt):
        with client(run_world["runtimes"]["own"]) as http:
            return http.post(path(item), json=request, headers=headers(attempt))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, [key, key if same_key else uuid4()]))
    assert sorted(r.status_code for r in results) == ([200, 200] if same_key else [200, 409])
    if same_key:
        assert results[0].json() == results[1].json()
    else:
        error(next(r for r in results if r.status_code == 409), 409, "docx_conflict")
    assert len(receipts(run_world)) == 1
    assert (
        api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id).storage_revision
        == 2
    )


@pytest.mark.parametrize("after_commit", [False, True])
def test_commit_fault_and_retry_are_atomic(run_world, monkeypatch, after_commit):
    world = run_world
    item, key = seed(world), uuid4()
    with client(world["runtimes"]["own"]) as http:
        request = body(http, item)
    real = world["engine"].dialect.do_commit

    def fail(connection):
        if after_commit:
            real(connection)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(world["engine"].dialect, "do_commit", fail)
        with client(world["runtimes"]["own"]) as http:
            response = http.post(path(item), json=request, headers=headers(key))
            error(response, 503, "storage_unavailable")
            assert "SYNTHETIC_PRIVATE" not in response.text
    saved = api().get_docx(world["runtimes"]["own"], document_id=item.document_id)
    assert saved.storage_revision == (2 if after_commit else 1)
    assert saved.original_data == item.original_data
    assert len(receipts(world)) == int(after_commit)
    with client(world["runtimes"]["own"]) as http:
        response = http.post(path(item), json=request, headers=headers(key))
        assert response.status_code == 200 and response.json()["storage_revision"] == "2"
        assert http.post(path(item), json=request, headers=headers(key)).json() == response.json()
    assert len(receipts(world)) == 1
    assert (
        api().get_docx(world["runtimes"]["own"], document_id=item.document_id).storage_revision == 2
    )


def test_receipt_insert_failure_rolls_back_document(run_world):
    world, item = run_world, seed(run_world)
    with client(world["runtimes"]["own"]) as http:
        request = body(http, item)

        def fail(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("INSERT INTO DOCX_EDIT_RECEIPTS"):
                raise RuntimeError("SYNTHETIC_PRIVATE")

        event.listen(world["engine"], "before_cursor_execute", fail)
        try:
            response = http.post(path(item), json=request, headers=headers(uuid4()))
            error(response, 500, "storage_error")
            assert "SYNTHETIC_PRIVATE" not in response.text
        finally:
            event.remove(world["engine"], "before_cursor_execute", fail)
    assert receipts(world) == []
    assert api().get_docx(world["runtimes"]["own"], document_id=item.document_id) == item


@pytest.mark.parametrize(
    "fault,code,status",
    [
        ("revision", "docx_conflict", 409),
        ("source", "stale_source", 409),
        ("text", "text_mismatch", 409),
        ("newline", "unsupported_edit", 422),
        ("anchor", "invalid_anchor", 422),
    ],
)
def test_rejection_creates_neither_save_nor_receipt(run_world, fault, code, status):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        if fault == "revision":
            request["expected_storage_revision"] = "2"
        elif fault == "source":
            request["anchor"]["source_sha256"] = "0" * 64
        elif fault == "text":
            request["expected_text"] = "different"
        elif fault == "newline":
            request["replacement_text"] = "new\nline"
        else:
            request["anchor"]["path"] = [10000]
        error(http.post(path(item), json=request, headers=headers(uuid4())), status, code)
    assert receipts(run_world) == []
    assert api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == item


def test_scope_precedes_replay_and_key_is_per_document(run_world):
    item, other, key = seed(run_world), seed(run_world), uuid4()
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        assert http.post(path(item), json=request, headers=headers(key)).status_code == 200
        second = body(http, other)
        assert http.post(path(other), json=second, headers=headers(key)).status_code == 200
    for scope in ("peer", "foreign"):
        with client(run_world["runtimes"][scope]) as http:
            error(http.post(path(item), json=request, headers=headers(key)), 404, "not_found")
    assert len(receipts(run_world)) == 2


@pytest.mark.parametrize(
    "key", ["", "abc", str(uuid4()).upper(), " " + str(uuid4()), str(uuid4()).replace("-", "")]
)
def test_invalid_key_rejected_before_storage(run_world, key):
    with client(run_world["runtimes"]["own"]) as http:
        error(
            http.post(
                f"/docx-documents/{uuid4()}/text-edit", content=b"not json", headers=headers(key)
            ),
            422,
            "validation_error",
        )


def test_duplicate_header_and_openapi(run_world):
    with client(run_world["runtimes"]["own"]) as http:
        error(
            http.post(
                f"/docx-documents/{uuid4()}/text-edit",
                json={},
                headers=[("Idempotency-Key", str(uuid4())), ("Idempotency-Key", str(uuid4()))],
            ),
            422,
            "validation_error",
        )
        route = http.get("/openapi.json").json()["paths"][
            "/docx-documents/{document_id}/text-edit"
        ]["post"]
        parameter = next(p for p in route["parameters"] if p["name"] == "Idempotency-Key")
        assert parameter["in"] == "header" and parameter["required"] is False


@pytest.mark.parametrize("corruption", ["current", "receipt"])
def test_corruption_is_not_reported_as_success(run_world, corruption):
    item, key = seed(run_world), uuid4()
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        assert http.post(path(item), json=request, headers=headers(key)).status_code == 200
        with run_world["engine"].begin() as conn:
            conn.execute(
                text(
                    "UPDATE docx_documents SET current_sha256=:digest WHERE id=:id"
                    if corruption == "current"
                    else "UPDATE docx_edit_receipts SET current_sha256=:digest "
                    "WHERE document_id=:id"
                ),
                {"digest": "0" * 64, "id": item.document_id},
            )
        error(http.post(path(item), json=request, headers=headers(key)), 500, "storage_error")


def test_noop_at_last_revision_replays_and_old_writer_keeps_cas(run_world):
    item, key = seed(run_world), uuid4()
    with run_world["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_documents SET storage_revision=:r WHERE id=:id"),
            {"r": MAX - 1, "id": item.document_id},
        )
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        request["replacement_text"] = request["expected_text"]
        response = http.post(path(item), json=request, headers=headers(key))
        assert response.status_code == 200 and response.json()["storage_revision"] == str(MAX)
        assert http.post(path(item), json=request, headers=headers(key)).json() == response.json()
        error(http.post(path(item), json=request), 409, "docx_conflict")
    saved = api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
    assert saved.current_data == item.current_data and saved.storage_revision == MAX


def test_new_process_recovers_receipt_without_reapplying(run_world):
    item, key = seed(run_world), uuid4()
    with client(run_world["runtimes"]["own"]) as http:
        request = body(http, item)
        expected = http.post(path(item), json=request, headers=headers(key)).json()
    url, runtime = run_world["engine"].url, run_world["runtimes"]["own"]
    payload = {
        "user": str(runtime.user_id),
        "project": str(runtime.project_id),
        "username": url.username,
        "database": url.database,
        "host": url.query["host"],
        "path": path(item),
        "key": str(key),
        "request": request,
    }
    script = """
import json, sys
from pathlib import Path
from uuid import UUID
from sqlalchemy import URL, create_engine
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path.cwd() / 'src'))
from ara.app import create_app
from ara.documents.runtime import DocumentRuntime
p = json.loads(sys.stdin.read())
e = create_engine(URL.create('postgresql+psycopg', username=p['username'],
    database=p['database'], query={'host': p['host']}), hide_parameters=True)
try:
    r = DocumentRuntime(engine=e, user_id=UUID(p['user']),
        project_id=UUID(p['project']), mode='local')
    with TestClient(create_app(document_runtime=r)) as http:
        response = http.post(p['path'], json=p['request'], headers={'Idempotency-Key':p['key']})
        assert response.status_code == 200
        print(json.dumps(response.json()))
finally:
    e.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
    assert len(receipts(run_world)) == 1
