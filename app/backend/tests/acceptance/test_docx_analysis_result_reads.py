"""D: verified immutable public result reads, source identity and latest success."""

import importlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_docx_analysis_http import api_world as api_world
from test_docx_analysis_http import complete, poll, saved_request, started
from test_docx_analysis_supervisor_runtime import wait_for
from test_docx_editor_http import command, path, root

from ara.app import create_app


@pytest.mark.parametrize(
    "table,column",
    [
        ("docx_analysis_results", "result_data"),
        ("docx_analysis_results", "reply_data"),
        ("docx_analysis_attempts", "request_data"),
        ("docx_analysis_sources", "source_data"),
        ("docx_analysis_runs", "snapshot_data"),
    ],
)
def test_corruption_is_sanitized_and_never_serves_partial_findings(api_world, table, column):
    world, item, _, http, _, _ = api_world
    _, _, _, receipt = complete(api_world)
    with world["engine"].begin() as conn:
        conn.execute(text(f"UPDATE {table} SET {column} = :value"), {"value": b"SYNTHETIC_PRIVATE"})
    for url in (
        root(item) + "/analysis-result",
        root(item) + "/analysis-runs/" + receipt["run_id"] + "/result",
    ):
        response = http.get(url)
        assert response.status_code == 500, response.text
        assert response.json()["code"] == "storage_error"
        assert "SYNTHETIC_PRIVATE" not in response.text and "findings" not in response.text
        assert response.headers["cache-control"] == "no-store"
    with world["engine"].connect() as conn:
        assert bytes(conn.scalar(text(f"SELECT {column} FROM {table}"))) == b"SYNTHETIC_PRIVATE"
        assert conn.scalar(text("SELECT status FROM docx_analysis_runs")) == "succeeded"


def test_later_edit_and_failed_run_keep_old_verified_result(api_world, monkeypatch):
    world, item, _, http, _, p = api_world
    view, _, _, first = complete(api_world)
    before = http.get(root(item) + "/analysis-result").json()
    edited = http.post(
        path(item, view) + "/commands", json=command(view, "insert_text", "Updated ")
    ).json()
    _, body = saved_request(http, item, edited)
    after = http.get(root(item) + "/analysis-result").json()
    assert after["matches_saved_document"] is False
    assert int(after["current_storage_revision"]) > int(before["current_storage_revision"])
    assert (
        after["result"] == before["result"]
        and after["stored_result_sha256"] == before["stored_result_sha256"]
    )
    module = importlib.import_module("test_docx_analysis_http")
    monkeypatch.setattr(module, "reply_for", lambda request: b"invalid synthetic reply")
    location, _ = started(http, item, body)
    failed = poll(http, location)
    assert failed["state"]["status"] == "failed"
    latest = http.get(root(item) + "/analysis-result").json()
    assert latest["run"]["run_id"] == first["run_id"]
    assert latest["result"] == before["result"] and p.launches == 2
    assert (
        http.get(root(item) + "/analysis-runs/" + failed["run_id"] + "/result").status_code == 409
    )
    with world["engine"].connect() as conn:
        stored = conn.scalar(text("SELECT result_data FROM docx_analysis_results"))
    assert "private_provenance" in json.loads(bytes(stored))
    assert "private_provenance" not in latest["result"]


def test_retry_uses_pinned_source_not_later_saved_document(api_world):
    _, item, _, http, _, p = api_world
    view, body, _, first = complete(api_world)
    edited = http.post(
        path(item, view) + "/commands", json=command(view, "insert_text", "Changed ")
    ).json()
    saved_request(http, item, edited)
    retry = http.post(
        root(item) + "/analysis-runs/" + first["run_id"] + "/retry",
        json={"client_request_id": str(uuid4())},
    )
    assert retry.status_code == 202, retry.text
    second = poll(http, retry.headers["location"])
    assert second["state"]["status"] == "succeeded"
    assert second["state"]["storage_revision"] == body["storage_revision"]
    assert second["state"]["retry_of_run_id"] == first["run_id"]
    latest = http.get(root(item) + "/analysis-result").json()
    assert latest["run"]["run_id"] == second["run_id"]
    assert latest["matches_saved_document"] is False and p.launches == 2


def test_unknown_active_ticket_after_new_app_requires_recovery(api_world):
    world, item, _, http, s, p = api_world
    _, body = saved_request(http, item)
    p.done.clear()
    location, _ = started(http, item, body)
    wait_for(lambda: p.entered.is_set())
    run_id = http.get(location).json()["run_id"]
    assert http.get(root(item) + "/analysis-runs/" + run_id + "/result").status_code == 409
    with TestClient(
        create_app(document_runtime=world["runtimes"]["own"], analysis_supervisor=s)
    ) as other:
        assert other.get(location).json()["state"]["status"] == "running"
        response = other.post(location + "/stop", json={})
        assert response.status_code == 409 and response.json()["code"] == "recovery_required"
        assert not p.stopped.is_set()
    http.post(location + "/stop", json={})
    p.done.set()
    assert poll(http, location)["state"]["status"] == "cancelled"


def test_scope_rechecked_after_decode_outside_transaction(api_world, monkeypatch):
    world, item, _, http, _, _ = api_world
    complete(api_world)
    reads = importlib.import_module("ara.docx_analysis_api._reads")
    original = reads.restore_result

    def change_scope(*args, **kwargs):
        result = original(*args, **kwargs)
        with world["engine"].begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout='300ms'"))
            conn.execute(
                text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
                dict(
                    owner=world["runtimes"]["foreign"].user_id,
                    project=world["runtimes"]["own"].project_id,
                ),
            )
        return result

    monkeypatch.setattr(reads, "restore_result", change_scope)
    response = http.get(root(item) + "/analysis-result")
    assert response.status_code == 404 and "findings" not in response.text
