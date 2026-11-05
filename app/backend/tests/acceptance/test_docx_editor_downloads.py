"""Frozen E3A: exact scoped saved, RAM and recovery package downloads."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_docx_editor_http import command, control, opened, path, root
from test_docx_save_commit import prepared
from test_docx_text_edit import seed

from ara.app import create_app
from ara.docx_documents import get_docx, save_docx
from ara.docx_documents.save_commit import commit_save

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def working(view):
    return dict(
        expected_command_sequence=view["command_sequence"],
        expected_session_revision=view["document"]["session_revision"],
        expected_sha256=view["document"]["source_sha256"],
    )


def check_binary(response, data, kind):
    from hashlib import sha256

    assert response.status_code == 200, response.text
    assert response.content == data
    assert response.headers["content-type"] == MIME
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["etag"] == '"' + sha256(data).hexdigest() + '"'
    assert response.headers["x-ara-copy-kind"] == kind
    assert response.headers["content-disposition"].startswith('attachment; filename="')
    assert response.headers["content-disposition"].endswith('.docx"')


def test_saved_download_is_bound_to_confirmed_target_not_newer_current(run_world):
    runtime, item = run_world["runtimes"]["own"], seed(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        view, _ = opened(http, item)
        edited = http.post(
            path(item, view) + "/commands", json=command(view, "insert_text", "🧪 ")
        ).json()
        save = control(edited)
        saved = http.post(path(item, view) + "/save", json=save).json()
        expected = get_docx(runtime, document_id=item.document_id)
        save_docx(
            runtime,
            document_id=item.document_id,
            expected_storage_revision=2,
            data=item.current_data,
        )
        body = {
            **save,
            "expected_command_sequence": saved["command_sequence"],
            "expected_session_revision": saved["document"]["session_revision"],
        }
        response = http.post(path(item, view) + "/saved-content", json=body)
        check_binary(response, expected.current_data, "saved")
        assert response.headers["x-ara-storage-revision"] == "2"
        assert get_docx(runtime, document_id=item.document_id).storage_revision == 3
        assert http.post(path(item, view) + "/saved-content", json=save).status_code == 409


def test_ram_download_preserves_unsaved_copy_history_and_checkpoint(run_world):
    runtime, item = run_world["runtimes"]["own"], seed(run_world)
    app = create_app(document_runtime=runtime)
    with TestClient(app) as http:
        view, _ = opened(http, item)
        edited = http.post(
            path(item, view) + "/commands", json=command(view, "insert_text", "Unsaved ")
        ).json()
        registry = app.state.docx_editor_registry
        before = registry.snapshot(
            document_id=item.document_id, session_id=UUID(view["session_id"])
        )
        response = http.post(path(item, view) + "/working-content", json=working(edited))
        check_binary(response, before.editor.document.data, "working")
        assert response.headers["x-ara-command-sequence"] == "1"
        assert response.headers["x-ara-session-revision"] == "1"
        assert http.get(path(item, view)).json() == edited
        assert get_docx(runtime, document_id=item.document_id) == item
        with runtime.engine.connect() as conn:
            assert conn.execute(
                text("SELECT phase, checkpoint_revision FROM docx_editor_checkpoints")
            ).one() == ("empty", 1)
        assert (
            http.post(path(item, view) + "/working-content", json=working(view)).status_code == 409
        )


@pytest.mark.parametrize("committed", [False, True])
def test_pending_download_never_commits_or_clears_even_with_corrupt_receipt(run_world, committed):
    runtime, item, pending = prepared(run_world)
    if committed:
        commit_save(runtime, handle=pending.handle)
        with runtime.engine.begin() as conn:
            conn.execute(
                text("UPDATE docx_edit_receipts SET request_sha256=:hash"), {"hash": "0" * 64}
            )
    before = get_docx(runtime, document_id=item.document_id)
    with TestClient(create_app(document_runtime=runtime)) as http:
        body = dict(
            expected_checkpoint_revision=str(pending.handle.prepared_checkpoint_revision),
            expected_sha256=pending.handle.working_sha256,
        )
        response = http.post(root(item) + "/editor-recovery/content", json=body)
        check_binary(response, pending.snapshot.checkpoint.working_data, "recovery")
        assert response.headers["x-ara-checkpoint-revision"] == str(
            pending.handle.prepared_checkpoint_revision
        )
        assert (
            http.post(
                root(item) + "/editor-recovery/content", json={**body, "expected_sha256": "0" * 64}
            ).status_code
            == 409
        )
    assert get_docx(runtime, document_id=item.document_id) == before
    with runtime.engine.connect() as conn:
        assert conn.execute(
            text("SELECT phase, checkpoint_revision FROM docx_editor_checkpoints")
        ).one() == ("pending", pending.handle.prepared_checkpoint_revision)


def test_live_ram_rescue_ignores_corrupt_receipt_and_foreign_checkpoint_fence(run_world):
    runtime, item, pending = prepared(run_world)
    app = create_app(document_runtime=runtime)
    with TestClient(app) as http:
        view, _ = opened(http, item, mode="recover")
        commit_save(runtime, handle=pending.handle)
        with runtime.engine.begin() as conn:
            conn.execute(
                text("UPDATE docx_edit_receipts SET current_size_bytes=current_size_bytes+1")
            )
        assert http.get(path(item, view)).status_code == 500
        response = http.post(path(item, view) + "/working-content", json=working(view))
        check_binary(response, pending.snapshot.checkpoint.working_data, "working")
        with runtime.engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE docx_editor_checkpoints DROP CONSTRAINT ck_docx_editor_cp_version"
                )
            )
            conn.execute(text("UPDATE docx_editor_checkpoints SET format_version=2"))
        check_binary(
            http.post(path(item, view) + "/working-content", json=working(view)),
            pending.snapshot.checkpoint.working_data,
            "working",
        )


@pytest.mark.parametrize("suffix", ["working-content", "saved-content"])
def test_download_scope_precedes_expired_session_and_errors_are_no_store(run_world, suffix):
    item = seed(run_world)
    with TestClient(create_app(document_runtime=run_world["runtimes"]["own"])) as own:
        view, _ = opened(own, item)
    with TestClient(create_app(document_runtime=run_world["runtimes"]["foreign"])) as foreign:
        response = foreign.post(
            path(item, view) + "/" + suffix,
            json=working(view) if suffix.startswith("working") else control(view),
        )
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    with TestClient(create_app(document_runtime=run_world["runtimes"]["own"])) as fresh:
        response = fresh.post(
            path(item, view) + "/" + suffix,
            json=working(view) if suffix.startswith("working") else control(view),
        )
        assert response.status_code == 410


def test_recovery_absent_empty_and_malformed_downloads_do_not_initialize_or_dispatch(
    run_world, monkeypatch
):
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    with TestClient(app) as http:
        target = root(item) + "/editor-recovery/content"
        body = dict(expected_checkpoint_revision="0", expected_sha256=item.current_sha256)
        assert http.post(target, json=body).status_code == 409
        with run_world["engine"].connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM docx_editor_checkpoints")) == 0
        view, _ = opened(http, item)
        assert (
            http.post(target, json={**body, "expected_checkpoint_revision": "1"}).status_code == 409
        )

        def forbidden(**kwargs):
            raise AssertionError("Invalid body dispatched")

        monkeypatch.setattr(app.state.docx_editor_registry, "working_target", forbidden)
        for bad in (
            {**working(view), "expected_sha256": "X" * 64},
            {**working(view), "expected_command_sequence": 0},
            {**working(view), "data": "PRIVATE"},
        ):
            response = http.post(path(item, view) + "/working-content", json=bad)
            assert response.status_code == 422 and "PRIVATE" not in response.text


def test_download_openapi_binary_and_strict_request_bodies(run_world):
    with run_world["client"]() as http:
        schema = http.get("/openapi.json").json()
    base = "/docx-documents/{document_id}/editor-sessions/{session_id}/"
    for route in (
        base + "saved-content",
        base + "working-content",
        "/docx-documents/{document_id}/editor-recovery/content",
    ):
        endpoint = schema["paths"][route]["post"]
        assert set(endpoint["responses"]["200"]["content"]) == {MIME}
        assert endpoint["responses"]["200"]["content"][MIME]["schema"] == {
            "type": "string",
            "format": "binary",
        }
        assert endpoint["requestBody"]["required"] is True
        assert "409" in endpoint["responses"] and "503" in endpoint["responses"]
