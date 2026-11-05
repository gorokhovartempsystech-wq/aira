"""Frozen E3C: scoped SQL settings, real deadlines and durable timeout retry."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_docx_editor_downloads import working
from test_docx_editor_http import command, control, opened, path
from test_docx_text_edit import seed

from ara.app import create_app
from ara.docx_documents import get_docx


def settings(engine):
    with engine.begin() as conn:
        return conn.exec_driver_sql("SHOW lock_timeout").scalar_one(), conn.exec_driver_sql(
            "SHOW statement_timeout"
        ).scalar_one()


def test_scoped_runtime_is_inert_shares_pool_and_keeps_parent_settings(run_world, monkeypatch):
    from ara.docx_editor._deadlines import scoped_runtime

    runtime = run_world["runtimes"]["own"]
    baseline = settings(runtime.engine)

    def forbidden(*args, **kwargs):
        raise AssertionError("Construction attempted database I/O")

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine, "connect", forbidden)
        patch.setattr(runtime.engine, "dispose", forbidden)
        scoped = scoped_runtime(runtime)
    assert scoped is not runtime and scoped.engine is not runtime.engine
    assert (
        scoped.engine.pool is runtime.engine.pool
        and scoped.engine.dialect is runtime.engine.dialect
    )
    assert (scoped.user_id, scoped.project_id, scoped.mode) == (
        runtime.user_id,
        runtime.project_id,
        "local",
    )
    assert settings(scoped.engine) == ("5s", "15s")
    assert settings(scoped.engine) == ("5s", "15s")
    assert settings(runtime.engine) == baseline


def test_http_app_registry_uses_private_scope_wrapper_and_distinct_lifetime(run_world):
    runtime = run_world["runtimes"]["own"]
    first = create_app(document_runtime=runtime)
    second = create_app(document_runtime=runtime)
    a, b = first.state.docx_editor_registry._runtime, second.state.docx_editor_registry._runtime
    assert a.engine is not b.engine and a.engine is not runtime.engine
    assert a.engine.pool is b.engine.pool is runtime.engine.pool
    assert settings(a.engine) == settings(b.engine) == ("5s", "15s")
    with TestClient(first) as http:
        assert http.get("/health").status_code == 200
        assert http.get("/openapi.json").status_code == 200
    assert settings(runtime.engine) != ("5s", "15s")


def test_real_statement_deadline_cancels_query_and_allows_next_transaction(run_world):
    from ara.docx_editor._deadlines import scoped_runtime

    scoped = scoped_runtime(run_world["runtimes"]["own"])
    started = monotonic()
    with pytest.raises(OperationalError) as caught:
        with scoped.engine.begin() as conn:
            conn.exec_driver_sql("SELECT pg_sleep(30)")
    assert caught.value.orig.sqlstate == "57014"
    assert 12 <= monotonic() - started < 25
    assert settings(scoped.engine) == ("5s", "15s")


def test_http_lock_deadline_releases_gate_and_preserves_exact_ram(run_world):
    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    app = create_app(document_runtime=runtime)
    with TestClient(app) as http:
        view, _ = opened(http, item)
        with runtime.engine.begin() as blocked:
            blocked.execute(
                text("SELECT id FROM docx_documents WHERE id=:id FOR UPDATE"),
                {"id": item.document_id},
            )
            started = monotonic()
            with ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(
                    http.post, path(item, view) + "/working-content", json=working(view)
                ).result(12)
            assert 4 <= monotonic() - started < 12
            assert response.status_code == 503 and response.json()["code"] == "storage_unavailable"
            assert (
                response.json()["retryable"] is True
                and response.headers["cache-control"] == "no-store"
            )
        rescued = http.post(path(item, view) + "/working-content", json=working(view))
        assert rescued.status_code == 200 and rescued.content == item.current_data
        assert http.get(path(item, view)).json() == view


def test_timeout_after_prepare_keeps_attempt_and_retry_saves_exactly_once(run_world, monkeypatch):
    from ara.docx_editor import _save

    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    app = create_app(document_runtime=runtime)
    holder = runtime.engine.connect()
    locked = Event()
    real = _save.prepare_save

    def prepared_then_blocked(*args, **kwargs):
        result = real(*args, **kwargs)
        holder.begin()
        holder.execute(
            text("SELECT id FROM docx_documents WHERE id=:id FOR UPDATE"), {"id": item.document_id}
        )
        locked.set()
        return result

    try:
        with TestClient(app) as http:
            view, _ = opened(http, item)
            edited = http.post(
                path(item, view) + "/commands", json=command(view, "insert_text", "Once ")
            ).json()
            identity = control(edited)
            with monkeypatch.context() as patch:
                patch.setattr(_save, "prepare_save", prepared_then_blocked)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(http.post, path(item, view) + "/save", json=identity)
                    assert locked.wait(5)
                    busy = http.get(path(item, view))
                    assert busy.status_code == 503 and busy.json()["code"] == "editor_busy"
                    response = future.result(12)
                assert (
                    response.status_code == 503 and response.json()["code"] == "storage_unavailable"
                )
            holder.rollback()
            pending = http.get(path(item, view)).json()
            assert pending["state"] == "operation_pending" and pending["command_sequence"] == "1"
            assert pending["active_command"]["command_id"] == identity["command_id"]
            assert pending["active_command"]["stage"] == "save_pending"
            assert get_docx(runtime, document_id=item.document_id) == item
            saved = http.post(path(item, view) + "/save", json=identity)
            assert saved.status_code == 200 and saved.json()["base_storage_revision"] == "2"
            assert saved.json()["document"]["undo_depth"] == 1
            assert http.post(path(item, view) + "/save", json=identity).json() == saved.json()
            with runtime.engine.connect() as conn:
                assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1
                assert (
                    conn.scalar(text("SELECT checkpoint_revision FROM docx_editor_checkpoints"))
                    == 3
                )
    finally:
        holder.close()
