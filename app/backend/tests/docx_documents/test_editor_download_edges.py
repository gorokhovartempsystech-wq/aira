"""Download-only reads preserve scope, active attempts and immutable targets."""

from dataclasses import replace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from ara.app import create_app
from ara.documents.storage import DocumentError
from ara.docx_documents import get_docx, save_docx
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_editor_downloads import check_binary, working
from tests.acceptance.test_docx_editor_http import command, control, opened, path, root
from tests.acceptance.test_docx_text_edit import seed


def test_download_targets_expire_on_new_local_intent_and_survive_foreign_head(run_world):
    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    with TestClient(create_app(document_runtime=runtime)) as http:
        view, _ = opened(http, item)
        body = control(view)
        saved = http.post(path(item, view) + "/save", json=body).json()
        identity = {**body, "expected_command_sequence": saved["command_sequence"]}
        check_binary(
            http.post(path(item, view) + "/saved-content", json=identity),
            item.current_data,
            "saved",
        )
        edited = http.post(
            path(item, view) + "/commands", json=command(saved, "insert_text", "Local ")
        ).json()
        assert http.post(path(item, view) + "/saved-content", json=identity).status_code == 409
        save_docx(
            runtime,
            document_id=item.document_id,
            expected_storage_revision=1,
            data=item.current_data,
        )
        assert http.get(path(item, view)).json()["state"] == "conflict"
        rescue = http.post(path(item, view) + "/working-content", json=working(edited))
        assert rescue.status_code == 200 and rescue.headers["x-ara-copy-kind"] == "working"
        assert rescue.content != item.current_data


def test_uncertain_active_save_can_be_rescued_without_dispatching_save_again(
    run_world, monkeypatch
):
    from ara.docx_editor import _save

    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    app = create_app(document_runtime=runtime)
    with TestClient(app) as http:
        view, _ = opened(http, item)
        edited = http.post(
            path(item, view) + "/commands", json=command(view, "insert_text", "Pending ")
        ).json()
        calls = []

        def unavailable(*args, **kwargs):
            calls.append(1)
            raise DocumentError(503, "storage_unavailable", "Unavailable", True)

        monkeypatch.setattr(_save, "commit_save", unavailable)
        assert http.post(path(item, view) + "/save", json=control(edited)).status_code == 503
        response = http.post(path(item, view) + "/working-content", json=working(edited))
        assert response.status_code == 200 and len(calls) == 1
        state = http.get(path(item, view)).json()
        assert state["state"] == "operation_pending" and state["command_sequence"] == "1"
        assert state["active_command"]["stage"] == "save_pending"
        assert get_docx(runtime, document_id=item.document_id) == item


def test_recovery_working_copy_corrupt_metadata_refused_without_writes(run_world):
    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    with TestClient(create_app(document_runtime=runtime)) as http:
        view, _ = opened(http, item)
        edited = http.post(
            path(item, view) + "/commands", json=command(view, "insert_text", "Draft ")
        ).json()
        saved = http.post(path(item, view) + "/checkpoint", json=control(edited)).json()
        body = dict(
            expected_checkpoint_revision=saved["checkpoint_revision"],
            expected_sha256=saved["document"]["source_sha256"],
        )
        downloaded = http.post(root(item) + "/editor-recovery/content", json=body)
        assert downloaded.status_code == 200
        with runtime.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE docx_editor_checkpoints SET metadata=jsonb_set("
                    "metadata, '{origin,position_id}', '\"bad\"')"
                )
            )
        assert http.post(root(item) + "/editor-recovery/content", json=body).status_code == 500
        assert get_docx(runtime, document_id=item.document_id) == item
        assert (
            http.post(path(item, view) + "/working-content", json=working(saved)).content
            == downloaded.content
        )


def test_read_commit_failure_returns_no_binary_and_preserves_actor(run_world, monkeypatch):
    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    app = create_app(document_runtime=runtime)
    with TestClient(app) as http:
        view, _ = opened(http, item)
        real = runtime.engine.dialect.do_commit

        def broken(connection):
            raise OperationalError("COMMIT", {}, Exception("PRIVATE"))

        with monkeypatch.context() as patch:
            patch.setattr(runtime.engine.dialect, "do_commit", broken)
            response = http.post(path(item, view) + "/working-content", json=working(view))
            assert response.status_code == 503 and "PRIVATE" not in response.text
        assert runtime.engine.dialect.do_commit == real
        check_binary(
            http.post(path(item, view) + "/working-content", json=working(view)),
            item.current_data,
            "working",
        )
        assert http.get(path(item, view)).json() == view


def test_working_rescue_only_selects_scope_and_ignores_mutated_caller_context(run_world):
    item, runtime = seed(run_world), replace(run_world["runtimes"]["own"])
    app = create_app(document_runtime=runtime)
    with TestClient(app) as http:
        view, _ = opened(http, item)
        statements = []

        def collect(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lower())

        object.__setattr__(runtime, "project_id", run_world["projects"]["foreign"])
        event.listen(runtime.engine, "before_cursor_execute", collect)
        try:
            check_binary(
                http.post(path(item, view) + "/working-content", json=working(view)),
                item.current_data,
                "working",
            )
        finally:
            event.remove(runtime.engine, "before_cursor_execute", collect)
        joined = " ".join(statements)
        assert "docx_editor_checkpoints" not in joined and "docx_edit_receipts" not in joined
        assert "current_data" not in joined and "original_data" not in joined
        target = app.state.docx_editor_registry.working_target(
            document_id=item.document_id,
            session_id=UUID(view["session_id"]),
            expected_command_sequence=0,
            expected_session_revision=0,
            expected_sha256=item.current_sha256,
        )
        assert "data=" not in repr(target) and "PK" not in repr(target)


def test_download_installation_is_explicit_and_unique():
    from ara.config import ConfigurationError
    from ara.docx_editor.http_downloads import install_editor_downloads

    app = create_app()
    assert not hasattr(app.state, "docx_editor_registry")
    assert not any("editor-" in r.path for r in app.routes)
    with pytest.raises(ConfigurationError):
        install_editor_downloads(app)
