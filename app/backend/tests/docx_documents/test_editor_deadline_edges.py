"""SQL limits stay local even when all routes share a physical pooled connection."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from ara.app import create_app
from ara.docx_editor import EditorRegistry
from ara.docx_editor._deadlines import scoped_runtime
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_editor_deadlines import settings
from tests.acceptance.test_docx_editor_discard_http import discard, prepare_plan
from tests.acceptance.test_docx_editor_downloads import working
from tests.acceptance.test_docx_editor_http import command, control, opened, path, root
from tests.acceptance.test_docx_text_edit import seed


def test_transaction_local_settings_reset_after_commit_and_rollback_on_same_connection(run_world):
    runtime = run_world["runtimes"]["own"]
    pooled = create_engine(runtime.engine.url, pool_size=1, max_overflow=0, hide_parameters=True)
    try:
        scoped = scoped_runtime(replace(runtime, engine=pooled))
        baseline = settings(pooled)
        with pooled.begin() as conn:
            pid = conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
        for outcome in ("commit", "rollback"):
            conn = scoped.engine.connect()
            try:
                transaction = conn.begin()
                assert conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() == pid
                assert conn.exec_driver_sql("SHOW lock_timeout").scalar_one() == "5s"
                assert conn.exec_driver_sql("SHOW statement_timeout").scalar_one() == "15s"
                getattr(transaction, outcome)()
            finally:
                conn.close()
            assert settings(pooled) == baseline
            with pooled.begin() as conn:
                assert conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one() == pid
        assert settings(scoped.engine) == ("5s", "15s")
        assert settings(pooled) == baseline
    finally:
        pooled.dispose()


def test_json_binary_and_discard_use_wrapper_while_old_api_and_direct_registry_do_not(run_world):
    runtime, item = run_world["runtimes"]["own"], seed(run_world)
    app = create_app(document_runtime=runtime)
    scoped_engine = app.state.docx_editor_registry._runtime.engine
    statements = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        statements.append((conn.engine, statement))

    event.listen(runtime.engine, "before_cursor_execute", collect)
    try:
        with TestClient(app) as http:
            view, _ = opened(http, item)
            edited = http.post(
                path(item, view) + "/commands", json=command(view, "insert_text", "Scoped ")
            ).json()
            identity = control(edited)
            saved = http.post(path(item, view) + "/save", json=identity).json()
            actions = [
                lambda: http.get(path(item, view)),
                lambda: http.get(path(item, view) + "/view"),
                lambda: http.post(path(item, view) + "/working-content", json=working(saved)),
                lambda: http.post(
                    path(item, view) + "/saved-content",
                    json={**identity, "expected_command_sequence": saved["command_sequence"]},
                ),
                lambda: http.post(
                    root(item) + "/editor-recovery/content",
                    json=dict(
                        expected_checkpoint_revision="3",
                        expected_sha256=saved["document"]["source_sha256"],
                    ),
                ),
            ]
            for action in actions:
                statements.clear()
                response = action()
                assert response.status_code == 200, response.text
                assert statements and all(engine is scoped_engine for engine, _ in statements)
                assert any("SET LOCAL lock_timeout" in sql for _, sql in statements)
            statements.clear()
            plan, _ = prepare_plan(http, item, 3)
            assert discard(http, item, plan).status_code == 200
            assert statements and all(engine is scoped_engine for engine, _ in statements)
            statements.clear()
            assert http.get(root(item)).status_code == 200
            assert statements and all(engine is runtime.engine for engine, _ in statements)
            assert not any("SET LOCAL" in sql for _, sql in statements)
        direct = EditorRegistry(runtime)
        statements.clear()
        direct.inspect_recovery(document_id=item.document_id)
        assert statements and all(engine is runtime.engine for engine, _ in statements)
        assert not any("SET LOCAL" in sql for _, sql in statements)
    finally:
        event.remove(runtime.engine, "before_cursor_execute", collect)


def test_deadline_scope_construction_does_not_acquire_connection_or_dispose_caller(
    run_world, monkeypatch
):
    runtime = run_world["runtimes"]["own"]

    def forbidden(*args, **kwargs):
        raise AssertionError("I/O during scoped construction/OpenAPI")

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.pool, "connect", forbidden)
        patch.setattr(runtime.engine, "dispose", forbidden)
        app = create_app(document_runtime=runtime)
        assert app.openapi()["paths"]["/health"]
    assert settings(runtime.engine) != ("5s", "15s")


@pytest.mark.parametrize("value", [None, object(), {}, "PRIVATE"])
def test_invalid_context_is_rejected_without_runtime_io(value):
    from ara.config import ConfigurationError

    with pytest.raises(ConfigurationError) as caught:
        scoped_runtime(value)
    assert "PRIVATE" not in str(caught.value)
