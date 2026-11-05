"""Frozen D03-16D3B: exact dirty save and recovery under lost acknowledgements."""

import importlib
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_docx_checkpoints import reject
from test_docx_editor_commands import command, opened
from test_docx_editor_controls import control
from test_docx_editor_registry import api, opening
from test_docx_save_commit import prepared

from ara.docx_documents import get_docx, save_docx
from ara.docx_documents.save_reconcile import reconcile_save


def saved_target(registry, view):
    return registry.saved_target(
        document_id=view.document_id,
        session_id=view.session_id,
        command_id=view.last_command.command_id,
        expected_command_sequence=view.command_sequence,
        expected_session_revision=view.editor.document.revision,
    )


def test_dirty_save_retains_exact_history_and_target_survives_foreign_head(run_world):
    runtime, item, registry, view = opened(run_world)
    edited = registry.command(**command(registry, view, "paste_text", "One\nTwo 🧪"))
    request = control(edited)
    saved = registry.save(**request)
    assert saved.command_sequence == edited.command_sequence + 1 and saved.active_command is None
    assert not saved.editor.document.is_dirty and saved.editor.selection == edited.editor.selection
    assert saved.editor.document.revision == edited.editor.document.revision
    assert saved.editor.document.undo_depth == edited.editor.document.undo_depth
    current = get_docx(runtime, document_id=item.document_id)
    assert current.current_data == edited.editor.document.data and current.storage_revision == 2
    assert current.original_data == item.original_data
    assert registry.save(**request) == saved and registry.reconcile(**request) == saved
    target = saved_target(registry, saved)
    assert (
        target.data == current.current_data
        and target.storage_revision == 2
        and target.sha256 == current.current_sha256
    )
    newer = save_docx(
        runtime, document_id=item.document_id, expected_storage_revision=2, data=item.original_data
    )
    assert saved_target(registry, saved) == target
    assert registry.save(**request).state == "conflict"
    assert get_docx(runtime, document_id=item.document_id) == newer


def test_save_mark_preserves_undo_dirty_redo_clean_and_supersedes_binary_target(run_world):
    _, item, registry, view = opened(run_world)
    edited = registry.command(**command(registry, view, "insert_text", "New "))
    saved = registry.save(**control(edited))
    undo = registry.command(**command(registry, saved, "undo"))
    assert undo.editor.document.data == item.current_data and undo.editor.document.is_dirty
    reject(lambda: saved_target(registry, saved), "stale_command")
    redo = registry.command(**command(registry, undo, "redo"))
    assert (
        redo.editor.document.data == saved.editor.document.data
        and not redo.editor.document.is_dirty
    )


def test_clean_save_has_bound_target_without_current_revision_or_receipt(run_world):
    runtime, item, registry, view = opened(run_world)
    saved = registry.save(**control(view))
    target = saved_target(registry, saved)
    assert target.data == item.current_data and target.storage_revision == 1
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0
    changed = registry.checkpoint(**control(saved))
    reject(lambda: saved_target(registry, saved), "stale_command")
    assert changed.command_sequence == 2


@pytest.mark.parametrize("step", [2, 3, 4])
@pytest.mark.parametrize("after_commit", [False, True])
def test_all_save_transaction_cuts_reconcile_same_operation_once(
    run_world, monkeypatch, step, after_commit
):
    runtime, item, registry, view = opened(run_world)
    edited = registry.command(**command(registry, view, "insert_text", "New "))
    request = control(edited)
    real, count = runtime.engine.dialect.do_commit, 0

    def fail(conn):
        nonlocal count
        count += 1
        if count == step:
            if after_commit:
                real(conn)
            raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))
        real(conn)

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: registry.save(**request), "storage_unavailable", 503)
    frozen = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert frozen.editor == edited.editor and frozen.command_sequence == edited.command_sequence
    assert frozen.state == "operation_pending" and frozen.active_command.operation_id is not None
    reject(
        lambda: registry.command(**command(registry, frozen, "insert_text", "X")),
        "editor_operation_pending",
    )
    result = registry.reconcile(**request)
    assert (
        result.command_sequence == edited.command_sequence + 1
        and not result.editor.document.is_dirty
    )
    assert result.checkpoint_revision == 3 and result.active_command is None
    assert registry.save(**request) == result
    assert (
        get_docx(runtime, document_id=item.document_id).current_data == edited.editor.document.data
    )
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1


def test_reply_failure_after_finalize_is_replayable_without_another_save(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    edited = registry.command(**command(registry, view, "insert_text", "New "))
    request = control(edited)
    models = importlib.import_module("ara.docx_editor._models")
    real = models.EditorView.__post_init__

    def fail(self):
        if self.command_sequence == 2:
            raise RuntimeError("SYNTHETIC_PRIVATE")
        real(self)

    with monkeypatch.context() as patch:
        patch.setattr(models.EditorView, "__post_init__", fail)
        reject(lambda: registry.save(**request), "editor_error", 500)
    current = get_docx(runtime, document_id=item.document_id)
    assert current.storage_revision == 2
    assert (
        registry.snapshot(
            document_id=item.document_id, session_id=view.session_id
        ).active_command.save_state
        == "committed"
    )
    result = registry.reconcile(**request)
    assert not result.editor.document.is_dirty and result.command_sequence == 2
    assert get_docx(runtime, document_id=item.document_id) == current


@pytest.mark.parametrize("already_finalized", [False, True])
def test_recovered_pending_uses_new_local_target_and_old_durable_handle(
    run_world, already_finalized
):
    runtime, item, pending = prepared(run_world)
    registry = api().EditorRegistry(runtime)
    view = registry.open(**opening(registry, item, mode="recover")).view
    assert (
        view.editor.document.revision == 0
        and view.session_id != pending.handle.metadata.origin.session_id
    )
    if already_finalized:
        reconcile_save(runtime, handle=pending.handle, request_id=uuid4())
    result = registry.reconcile(**control(view))
    assert result.editor.document.revision == 0 and result.editor.position_id == 0
    assert not result.editor.document.is_dirty and result.editor.document.undo_depth == 0
    assert result.base_storage_revision == 2 and result.checkpoint_revision == 3
    assert saved_target(registry, result).data == view.editor.document.data


def test_expected_handle_exists_before_prepare_and_completed_elsewhere_is_recognized(
    run_world, monkeypatch
):
    runtime, item, registry, view = opened(run_world)
    edited = registry.command(**command(registry, view, "insert_text", "New "))
    module = importlib.import_module("ara.docx_editor._save")
    real = module.prepare_save
    request = control(edited)
    seen = []

    def lose(*args, **kwargs):
        attempt = registry._actors[(item.document_id, view.session_id)].state.active
        attempt.handle.__post_init__()
        seen.append(deepcopy(attempt.handle))
        prepared_result = real(*args, **kwargs)
        assert prepared_result.handle == attempt.handle
        reconcile_save(runtime, handle=attempt.handle, request_id=uuid4())
        from ara.documents.storage import DocumentError

        raise DocumentError(503, "storage_unavailable", "Synthetic unknown outcome", True)

    with monkeypatch.context() as patch:
        patch.setattr(module, "prepare_save", lose)
        reject(lambda: registry.save(**request), "storage_unavailable", 503)
    result = registry.reconcile(**request)
    assert not result.editor.document.is_dirty and result.base_storage_revision == 2
    assert get_docx(runtime, document_id=item.document_id).storage_revision == 2
    assert seen[0].working_sha256 == result.editor.document.projection.source.sha256
