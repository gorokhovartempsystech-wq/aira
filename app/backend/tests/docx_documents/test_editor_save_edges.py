"""Saved snapshots, foreign draft proof, counter boundaries and process recovery."""

import importlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from ara.docx_documents import get_docx, save_docx
from ara.docx_documents._dto import MAX_REVISION
from ara.docx_documents.checkpoints import discard_checkpoint
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import api as checkpoints
from tests.acceptance.test_docx_checkpoints import reject
from tests.acceptance.test_docx_editor_commands import command, opened
from tests.acceptance.test_docx_editor_controls import control
from tests.acceptance.test_docx_editor_registry import opening
from tests.acceptance.test_docx_editor_save import saved_target
from tests.acceptance.test_docx_recovery import request as legacy_request
from tests.acceptance.test_docx_text_edit import client


def freeze(registry, view, monkeypatch, *, finalized=False):
    module = importlib.import_module("ara.docx_editor._save")
    real = module.finalize_save
    request = control(view)

    def fail(*args, **kwargs):
        if finalized:
            real(*args, **kwargs)
        from ara.documents.storage import DocumentError

        raise DocumentError(503, "storage_unavailable", "Synthetic unknown outcome", True)

    with monkeypatch.context() as patch:
        patch.setattr(module, "finalize_save", fail)
        reject(lambda: registry.save(**request), "storage_unavailable", 503)
    return request


def test_foreign_current_after_commit_reports_confirmation_without_false_saved(
    run_world, monkeypatch
):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = freeze(registry, view, monkeypatch)
    newer = save_docx(
        runtime, document_id=item.document_id, expected_storage_revision=2, data=item.original_data
    )
    local = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert local.state == "conflict" and local.editor == view.editor
    assert local.active_command.save_state == "committed_outdated"
    reject(lambda: registry.reconcile(**request), "docx_conflict")
    assert get_docx(runtime, document_id=item.document_id) == newer
    registry.close(**control(local), mode="release_local")
    assert get_docx(runtime, document_id=item.document_id) == newer


def test_receipt_confirmation_does_not_read_somebody_elses_legacy_draft(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = freeze(registry, view, monkeypatch, finalized=True)
    discard_checkpoint(
        runtime, document_id=item.document_id, expected_checkpoint_revision=3, request_id=uuid4()
    )
    with client(runtime) as http:
        assert (
            http.put(
                f"/docx-documents/{item.document_id}/draft", json=legacy_request(http, item)
            ).status_code
            == 200
        )
    before = get_docx(runtime, document_id=item.document_id)
    local = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert local.state == "conflict" and local.active_command.save_state == "committed"
    assert local.editor.document.is_dirty
    reject(lambda: registry.reconcile(**request), "checkpoint_conflict")
    registry.close(**control(local), mode="release_local")
    assert get_docx(runtime, document_id=item.document_id) == before


def test_stored_corrupt_receipt_is_not_repaired_or_marked_saved(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = freeze(registry, view, monkeypatch)
    with runtime.engine.begin() as conn:
        conn.execute(text("UPDATE docx_edit_receipts SET current_size_bytes=current_size_bytes+1"))
    reject(
        lambda: registry.snapshot(document_id=item.document_id, session_id=view.session_id),
        "storage_error",
        500,
    )
    reject(lambda: registry.reconcile(**request), "storage_error", 500)
    actor = registry._actors[(item.document_id, view.session_id)]
    assert actor.state.editor.snapshot() == view.editor and actor.state.active is not None
    registry.close(**control(view), mode="release_local")
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1


def test_tampered_prepare_reply_does_not_change_immutable_expected_handle(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = control(view)
    module = importlib.import_module("ara.docx_editor._save")
    real = module.prepare_save

    def damaged(*args, **kwargs):
        result = real(*args, **kwargs)
        object.__setattr__(result.handle, "working_sha256", "f" * 64)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(module, "prepare_save", damaged)
        reject(lambda: registry.save(**request), "editor_error", 500)
    result = registry.reconcile(**request)
    assert not result.editor.document.is_dirty and result.base_storage_revision == 2
    assert get_docx(runtime, document_id=item.document_id).current_data == view.editor.document.data


def test_target_dto_failure_after_commit_and_output_isolation(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = control(view)
    models = importlib.import_module("ara.docx_editor._models")

    def fail(self):
        raise RuntimeError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(models.SavedTarget, "__post_init__", fail)
        reject(lambda: registry.save(**request), "editor_error", 500)
    assert get_docx(runtime, document_id=item.document_id).storage_revision == 2
    result = registry.reconcile(**request)
    target = saved_target(registry, result)
    original = deepcopy(target)
    object.__setattr__(target, "data", b"broken")
    assert saved_target(registry, result) == original
    with pytest.raises(ValueError):
        target.__post_init__()


@pytest.mark.parametrize("initial_cp", [MAX_REVISION - 2, MAX_REVISION - 1])
def test_final_checkpoint_boundary_and_successful_replay(run_world, initial_cp):
    runtime, item, registry, view = opened(run_world)
    registry.close(**control(view), mode="release_local")
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_editor_checkpoints SET checkpoint_revision=:r"), {"r": initial_cp}
        )
    view = registry.open(**opening(registry, item)).view
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = control(view)
    if initial_cp == MAX_REVISION - 1:
        reject(lambda: registry.save(**request), "revision_exhausted")
        assert registry._actors[(item.document_id, view.session_id)].state.active is None
        assert get_docx(runtime, document_id=item.document_id).storage_revision == 1
    else:
        saved = registry.save(**request)
        assert saved.checkpoint_revision == MAX_REVISION and not saved.editor.document.is_dirty
        assert registry.save(**request) == saved
        assert saved_target(registry, saved).storage_revision == 2
        reject(lambda: registry.checkpoint(**control(saved)), "revision_exhausted")


def test_saved_target_scope_and_read_only_active_proof(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = freeze(registry, view, monkeypatch)
    statements = []

    def trace(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(runtime.engine, "before_cursor_execute", trace)
    try:
        local = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
        assert local.active_command.save_state == "committed"
    finally:
        event.remove(runtime.engine, "before_cursor_execute", trace)
    assert statements and set(statements) == {"SELECT"}
    saved = registry.reconcile(**request)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE projects SET owner_id=:u WHERE id=:p"),
            {"u": run_world["owners"]["foreign"], "p": runtime.project_id},
        )
    reject(lambda: saved_target(registry, saved), "not_found", 404)


def test_retained_admission_failure_happens_before_attempt_or_sql_save(run_world):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    registry._budget.maximum = 1
    reject(lambda: registry.save(**control(view)), "editor_limit_exceeded", 413)
    actor = registry._actors[(item.document_id, view.session_id)]
    assert actor.state.active is None and actor.state.editor.snapshot() == view.editor
    assert get_docx(runtime, document_id=item.document_id).storage_revision == 1
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.phase
        == "empty"
    )
    registry._budget.maximum = 268435456
    assert not registry.save(**control(view)).editor.document.is_dirty


def test_new_process_reconciles_same_receipt_with_new_local_revision(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request = freeze(registry, view, monkeypatch)
    payload = {
        "url": runtime.engine.url.render_as_string(hide_password=False),
        "user": str(runtime.user_id),
        "project": str(runtime.project_id),
        "doc": str(item.document_id),
    }
    script = """
import json,sys
from uuid import UUID,uuid4
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ara.documents.runtime import DocumentRuntime
from ara.docx_editor import EditorRegistry
p=json.load(sys.stdin);e=create_engine(p['url'],poolclass=NullPool,hide_parameters=True)
try:
 r=EditorRegistry(DocumentRuntime(engine=e,user_id=UUID(p['user']),project_id=UUID(p['project']),mode='local'))
 d=UUID(p['doc']);s=r.inspect_recovery(document_id=d)
 v=r.open(document_id=d,registry_id=s.registry_id,client_open_id=uuid4(),expected_open_sequence=0,expected_checkpoint_revision=s.checkpoint_revision,mode='recover').view
 v=r.reconcile(document_id=d,session_id=v.session_id,command_id=uuid4(),expected_command_sequence=0,expected_session_revision=0)
 print(json.dumps({'registry':str(v.registry_id),'revision':v.editor.document.revision,'history':v.editor.document.undo_depth,'dirty':v.editor.document.is_dirty,'storage':v.base_storage_revision}))
finally:e.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(payload),
        env={"PYTHONPATH": str(Path.cwd() / "src")},
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert (
        observed["registry"] != str(view.registry_id)
        and observed["revision"] == observed["history"] == 0
    )
    assert not observed["dirty"] and observed["storage"] == 2
    saved = registry.reconcile(**request)
    assert not saved.editor.document.is_dirty and saved.editor.document.undo_depth == 1
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1


def test_save_module_first_import_is_inert():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy,contextlib,functools
import hashlib,re,zipfile,xml.etree.ElementTree,typing,datetime,threading,inspect
from pathlib import Path
import sqlalchemy,psycopg,ara.docx_editor
assert 'ara.docx_editor._save' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
 setattr(obj,name,forbidden)
import ara.docx_editor._save
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={"PYTHONPATH": str(Path.cwd() / "src")},
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout


def test_latest_native_retry_during_own_save_reads_full_proof(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    native = command(registry, view, "insert_text", "Once ")
    view = registry.command(**native)
    request = freeze(registry, view, monkeypatch)
    replay = registry.command(**native)
    assert replay.state == "operation_pending" and replay.editor == view.editor
    assert replay.active_command.save_state == "committed"
    assert not registry.reconcile(**request).editor.document.is_dirty
    assert get_docx(runtime, document_id=item.document_id).storage_revision == 2
