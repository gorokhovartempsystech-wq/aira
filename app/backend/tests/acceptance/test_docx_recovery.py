"""D03-05 independent acceptance for durable, scoped, CAS working copies."""

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from conftest import ROOT
from docx_storage_fixtures import api, raw
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from test_docx_http_reads import MAX, client, error
from test_docx_text_edit import body, seed
from test_migrations import _schema_signature

V7, V8 = "0007_docx_edit_receipts", "0008_docx_edit_drafts"


def path(item):
    return f"/docx-documents/{item.document_id}/draft"


def request(http, item):
    return {
        "expected_token": None,
        "token": str(uuid4()),
        "edit": body(http, item),
        "operation_id": None,
    }


def test_reopen_update_replay_and_delete_preserve_document(run_world):
    world, item = run_world, seed(run_world)
    with client(world["runtimes"]["own"]) as http:
        empty = http.get(path(item))
        assert empty.status_code == 200
        assert empty.json() == {"document_id": str(item.document_id), "draft": None}
        data = request(http, item)
        data["edit"]["replacement_text"] = "  Я🧪\r\n  <script>literal</script>  "
        data["operation_id"] = str(uuid4())
        response = http.put(path(item), json=data)
        assert response.status_code == 200, response.text
        original = response.json()
        assert set(original) == {"document_id", "draft"}
        assert set(original["draft"]) == {"token", "edit", "operation_id", "updated_at"}
        assert original["draft"]["edit"] == data["edit"]
        assert original["draft"]["operation_id"] == data["operation_id"]
        assert response.headers["cache-control"] == "no-store"
        assert http.put(path(item), json=data).json() == original
        changed = {**data, "expected_token": data["token"], "token": str(uuid4())}
        changed["edit"] = {**data["edit"], "replacement_text": "new copy"}
        assert http.put(path(item), json=changed).status_code == 200
        error(http.put(path(item), json=data), 409, "draft_conflict")
    engine = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with client(replace(world["runtimes"]["own"], engine=engine)) as reopened:
            record = reopened.get(path(item)).json()["draft"]
            assert record["edit"] == changed["edit"] and record["token"] == changed["token"]
            assert record["operation_id"] == data["operation_id"]
            stale = reopened.request("DELETE", path(item), json={"expected_token": data["token"]})
            error(stale, 409, "draft_conflict")
            for _ in range(2):
                deleted = reopened.request(
                    "DELETE", path(item), json={"expected_token": changed["token"]}
                )
                assert deleted.status_code == 204 and deleted.content == b""
                assert deleted.headers["cache-control"] == "no-store"
            assert reopened.get(path(item)).json()["draft"] is None
            error(reopened.put(path(item), json=changed), 409, "draft_conflict")
    finally:
        engine.dispose()
    assert api().get_docx(world["runtimes"]["own"], document_id=item.document_id) == item


@pytest.mark.parametrize("same", [False, True])
def test_concurrent_first_writers_are_cas_or_replay(run_world, same):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        first = request(http, item)
    second = deepcopy(first)
    if not same:
        second["token"] = str(uuid4())
        second["edit"]["replacement_text"] = "other window"

    def put(data):
        with client(run_world["runtimes"]["own"]) as http:
            return http.put(path(item), json=data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(put, [first, second]))
    assert sorted(r.status_code for r in results) == ([200, 200] if same else [200, 409])
    with run_world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_drafts")) == 1


@pytest.mark.parametrize("after_commit", [True, False])
def test_put_commit_ack_retry_and_rollback(run_world, monkeypatch, after_commit):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        data = request(http, item)
        real = run_world["engine"].dialect.do_commit

        def broken(connection):
            if after_commit:
                real(connection)
            raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

        with monkeypatch.context() as patch:
            patch.setattr(run_world["engine"].dialect, "do_commit", broken)
            response = http.put(path(item), json=data)
            error(response, 503, "storage_unavailable")
            assert "SYNTHETIC_PRIVATE" not in response.text
        assert (http.get(path(item)).json()["draft"] is not None) is after_commit
        assert http.put(path(item), json=data).status_code == 200
        assert http.get(path(item)).json()["draft"]["token"] == data["token"]
    assert api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id) == item


def test_stale_doc_and_last_bigint_edit_can_be_recovered_without_applying(run_world):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        data = request(http, item)
        data["edit"]["expected_storage_revision"] = str(MAX - 1)
        api().save_docx(
            run_world["runtimes"]["own"],
            document_id=item.document_id,
            expected_storage_revision=1,
            data=raw("fresh writer"),
        )
        assert http.put(path(item), json=data).status_code == 200
        assert http.get(path(item)).json()["draft"]["edit"] == data["edit"]
    saved = api().get_docx(run_world["runtimes"]["own"], document_id=item.document_id)
    assert saved.storage_revision == 2 and saved.current_data == raw("fresh writer")


def test_scope_precedes_read_write_delete(run_world):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        data = request(http, item)
        assert http.put(path(item), json=data).status_code == 200
    for scope in ("peer", "foreign"):
        with client(run_world["runtimes"][scope]) as http:
            for method, payload in (
                ("GET", None),
                ("PUT", data),
                ("DELETE", {"expected_token": data["token"]}),
            ):
                error(http.request(method, path(item), json=payload), 404, "not_found")


@pytest.mark.parametrize("fault", ["token", "expected", "same", "extra", "operation", "edit"])
def test_invalid_records_rejected_before_mutation(run_world, fault):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        data = request(http, item)
        if fault == "token":
            data["token"] = str(uuid4()).upper()
        elif fault == "expected":
            data["expected_token"] = 1
        elif fault == "same":
            data["expected_token"] = data["token"]
        elif fault == "extra":
            data["owner"] = str(uuid4())
        elif fault == "operation":
            data["operation_id"] = "invalid"
        else:
            data["edit"]["expected_storage_revision"] = 1
        error(http.put(path(item), json=data), 422, "validation_error")
        assert http.get(path(item)).json()["draft"] is None


def test_changed_payload_cannot_reuse_current_token_and_corruption_is_not_empty(run_world):
    item = seed(run_world)
    with client(run_world["runtimes"]["own"]) as http:
        data = request(http, item)
        assert http.put(path(item), json=data).status_code == 200
        changed = deepcopy(data)
        changed["edit"]["replacement_text"] += "!"
        error(http.put(path(item), json=changed), 409, "draft_conflict")
        with run_world["engine"].begin() as conn:
            conn.execute(
                text("UPDATE docx_edit_drafts SET payload='{}' WHERE document_id=:id"),
                {"id": item.document_id},
            )
        error(http.get(path(item)), 500, "storage_error")
        error(http.put(path(item), json=changed), 500, "storage_error")


@pytest.mark.parametrize(
    "content,headers,status,code",
    [
        (b'{"token":1,"token":2}', {}, 422, "validation_error"),
        (b'{"token":NaN}', {}, 422, "validation_error"),
        (b"\xff", {}, 422, "validation_error"),
        (b"{}", {"Content-Type": "text/plain"}, 415, "unsupported_media_type"),
        (b"{}", {"Content-Encoding": "gzip"}, 415, "unsupported_media_type"),
        (b"{}", {"Content-Length": "2097153"}, 413, "draft_request_too_large"),
        (b"x" * 2097153, {}, 413, "draft_request_too_large"),
    ],
)
def test_transport_is_bounded_and_strict(run_world, content, headers, status, code):
    with client(run_world["runtimes"]["own"]) as http:
        error(
            http.put(
                f"/docx-documents/{uuid4()}/draft",
                content=content,
                headers={"Content-Type": "application/json", **headers},
            ),
            status,
            code,
        )


def test_query_openapi_and_no_runtime():
    from ara.app import create_app
    from ara.documents.runtime import DocumentRuntime

    engine = create_engine("postgresql+psycopg://")
    runtime = DocumentRuntime(engine=engine, user_id=uuid4(), project_id=uuid4(), mode="local")
    try:
        with client(runtime) as http:
            error(http.get(f"/docx-documents/{uuid4()}/draft?other=1"), 422, "validation_error")
            schema = http.get("/openapi.json").json()
            route = schema["paths"]["/docx-documents/{document_id}/draft"]
            assert set(route) == {"get", "put", "delete"}
            for method in ("put", "delete"):
                assert route[method]["requestBody"]["required"] is True
        from fastapi.testclient import TestClient

        with TestClient(create_app()) as default:
            assert default.get(f"/docx-documents/{uuid4()}/draft").status_code == 404
    finally:
        engine.dispose()


def test_additive_migration_preserves_previous_schema_and_rows(empty_pg_engine, apply_migrations):
    from test_docx_storage_migrations import insert_row
    from test_draft_migrations import _draft, _seed_complete_history

    apply_migrations(empty_pg_engine, V7)
    with empty_pg_engine.begin() as conn:
        ids = _seed_complete_history(conn)
        _draft(conn, ids)
        project = conn.scalar(text("SELECT id FROM projects ORDER BY id LIMIT 1"))
        insert_row(conn, project)
        tables = inspect(conn).get_table_names()
        before = {
            t: conn.execute(text(f'SELECT * FROM "{t}"')).all()
            for t in tables
            if t != "alembic_version"
        }
        schema = json.loads(_schema_signature(conn))
    apply_migrations(empty_pg_engine, V8)
    apply_migrations(empty_pg_engine, V8)
    with empty_pg_engine.connect() as conn:
        after_schema = json.loads(_schema_signature(conn))
        assert "docx_edit_drafts" in after_schema
        del after_schema["docx_edit_drafts"]
        assert after_schema == schema
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == V8
        assert {t: conn.execute(text(f'SELECT * FROM "{t}"')).all() for t in before} == before
        columns = {c["name"]: c for c in inspect(conn).get_columns("docx_edit_drafts")}
        assert set(columns) == {"document_id", "token", "payload", "updated_at"}
        assert all(not c["nullable"] for c in columns.values())
        assert columns["updated_at"]["default"] == "clock_timestamp()"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with empty_pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, V7)
        assert json.loads(_schema_signature(conn)) == schema
        assert {t: conn.execute(text(f'SELECT * FROM "{t}"')).all() for t in before} == before
