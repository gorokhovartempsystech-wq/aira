"""Frozen D03-16D3A: stable checkpoint attempts across DB/RAM acknowledgement cuts."""

import importlib
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_docx_checkpoints import api as checkpoints
from test_docx_checkpoints import reject
from test_docx_editor_commands import command, opened
from test_docx_editor_registry import api, opening
from test_docx_save_commit import prepared

from ara.docx_documents import get_docx, save_docx
from ara.docx_documents._dto import MAX_REVISION


def control(view, **values):
    return dict(
        document_id=view.document_id,
        session_id=view.session_id,
        command_id=uuid4(),
        expected_command_sequence=view.command_sequence,
        expected_session_revision=view.editor.document.revision,
        **values,
    )


def test_dirty_checkpoint_is_exact_replayable_and_does_not_mark_current_saved(run_world):
    runtime, item, registry, view = opened(run_world)
    edited = registry.command(**command(registry, view, "paste_text", "One\nTwo"))
    request = control(edited)
    result = registry.checkpoint(**request)
    assert result.command_sequence == edited.command_sequence + 1
    assert result.editor == edited.editor and result.editor.document.is_dirty
    assert result.active_command is None and result.checkpoint_revision == 2
    assert registry.checkpoint(**request) == result
    assert registry.reconcile(**request) == result
    cp = checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
    assert (
        cp.working_data == edited.editor.document.data
        and cp.metadata.selection == edited.editor.selection
    )
    assert cp.metadata.origin.session_id == view.session_id
    assert cp.metadata.origin.session_revision == edited.editor.document.revision
    assert get_docx(runtime, document_id=item.document_id) == item
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0


def test_clean_save_only_checkpoints_and_dirty_save_is_not_claimed_ready(run_world):
    runtime, item, registry, view = opened(run_world)
    request = control(view)
    saved = registry.save(**request)
    assert not saved.editor.document.is_dirty and saved.command_sequence == 1
    assert saved.editor.document.revision == 0 and saved.checkpoint_revision == 2
    assert registry.save(**request) == saved
    changed = registry.command(**command(registry, saved, "insert_text", "New "))
    committed = registry.save(**control(changed))
    assert not committed.editor.document.is_dirty
    assert committed.editor.document.undo_depth == changed.editor.document.undo_depth
    assert committed.editor.selection == changed.editor.selection
    current = get_docx(runtime, document_id=item.document_id)
    assert current.storage_revision == item.storage_revision + 1
    assert current.current_data == changed.editor.document.data
    assert current.original_data == item.original_data
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1


@pytest.mark.parametrize("after_commit", [False, True])
def test_checkpoint_ack_loss_keeps_attempt_freezes_edits_and_reconciles_once(
    run_world, monkeypatch, after_commit
):
    runtime, item, registry, view = opened(run_world)
    changed = registry.command(**command(registry, view, "insert_text", "New "))
    request = control(changed)
    real, count = runtime.engine.dialect.do_commit, 0

    def fail(conn):
        nonlocal count
        count += 1
        if count == 2:
            if after_commit:
                real(conn)
            raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))
        real(conn)

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: registry.checkpoint(**request), "storage_unavailable", 503)
    frozen = registry.snapshot(document_id=view.document_id, session_id=view.session_id)
    assert frozen.state == "operation_pending" and frozen.editor == changed.editor
    assert frozen.command_sequence == changed.command_sequence
    assert frozen.active_command.command_id == request["command_id"]
    reject(
        lambda: registry.command(**command(registry, frozen, "insert_text", "X")),
        "editor_operation_pending",
    )
    reject(lambda: registry.checkpoint(**control(frozen)), "editor_operation_pending")
    cp = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    assert cp.checkpoint.checkpoint_revision == (2 if after_commit else 1)
    result = registry.reconcile(**request)
    assert result.command_sequence == changed.command_sequence + 1 and result.active_command is None
    assert result.checkpoint_revision == 2 and result.editor == changed.editor
    assert registry.checkpoint(**request) == result


def test_reply_failure_after_sql_commit_remains_recoverable(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    request = control(view)
    model = importlib.import_module("ara.docx_editor._models")
    real = model.EditorView.__post_init__

    def fail(self):
        if self.command_sequence == 1:
            raise RuntimeError("SYNTHETIC_PRIVATE")
        real(self)

    with monkeypatch.context() as patch:
        patch.setattr(model.EditorView, "__post_init__", fail)
        reject(lambda: registry.checkpoint(**request), "editor_error", 500)
    assert (
        checkpoints()
        .get_checkpoint(runtime, document_id=item.document_id)
        .checkpoint.checkpoint_revision
        == 2
    )
    assert (
        registry.snapshot(document_id=view.document_id, session_id=view.session_id).active_command
        is not None
    )
    assert registry.checkpoint(**request).command_sequence == 1


def test_altered_controls_and_superseded_commands_do_not_write(run_world):
    runtime, item, registry, view = opened(run_world)
    request = control(view)
    result = registry.checkpoint(**request)
    reject(lambda: registry.save(**request), "idempotency_conflict")
    reject(
        lambda: registry.checkpoint(**{**request, "expected_command_sequence": 1}),
        "idempotency_conflict",
    )
    second = registry.checkpoint(**control(result))
    reject(lambda: registry.checkpoint(**request), "stale_command")
    assert second.checkpoint_revision == 3
    assert (
        checkpoints()
        .get_checkpoint(runtime, document_id=item.document_id)
        .checkpoint.checkpoint_revision
        == 3
    )


def test_close_checkpoints_before_freeing_and_old_open_cannot_resurrect(run_world):
    runtime, item, registry, view = opened(run_world)
    opening_request = registry._actors[(item.document_id, view.session_id)].request
    edited = registry.command(**command(registry, view, "insert_text", "New "))
    request = control(edited)
    closed = registry.close(**request)
    assert closed.mode == "checkpoint" and closed.checkpoint_revision == 2
    reject(lambda: registry.close(**request), "editor_session_expired", 410)
    reject(
        lambda: registry.snapshot(document_id=item.document_id, session_id=view.session_id),
        "editor_session_expired",
        410,
    )
    fields = (
        "document_id",
        "registry_id",
        "client_open_id",
        "expected_open_sequence",
        "expected_checkpoint_revision",
        "mode",
    )
    reject(lambda: registry.open(**dict(zip(fields, opening_request, strict=True))), "stale_open")
    assert not registry._budget.groups and not registry._actors and not registry._opens
    recovered = registry.open(**opening(registry, item, mode="recover")).view
    assert (
        recovered.editor.document.data == edited.editor.document.data
        and recovered.editor.document.is_dirty
    )
    assert get_docx(runtime, document_id=item.document_id) == item


def test_explicit_release_preserves_checkpoint_even_for_pending_and_max(run_world):
    runtime, item, pending = prepared(run_world)
    registry = api().EditorRegistry(runtime)
    view = registry.open(**opening(registry, item, mode="recover")).view
    reject(lambda: registry.close(**control(view)), "editor_operation_pending")
    before = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    actor = registry._actors[(item.document_id, view.session_id)]
    actor.state = replace(actor.state, command_sequence=MAX_REVISION)
    request = control(replace(view, command_sequence=MAX_REVISION))
    closed = registry.close(**request, mode="release_local")
    assert closed.mode == "release_local" and closed.checkpoint_revision is None
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == before
    assert not registry._budget.groups


def test_foreign_current_keeps_local_copy_and_explicit_release_writes_nothing(run_world):
    runtime, item, registry, view = opened(run_world)
    edited = registry.command(**command(registry, view, "insert_text", "Local "))
    newer = save_docx(
        runtime, document_id=item.document_id, expected_storage_revision=1, data=item.current_data
    )
    reject(lambda: registry.checkpoint(**control(edited)), "docx_conflict")
    local = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert local.editor == edited.editor and local.state == "conflict"
    registry.close(**control(local), mode="release_local")
    assert get_docx(runtime, document_id=item.document_id) == newer


def test_scope_before_replay_or_expired_and_control_input_is_strict(run_world):
    runtime, item, registry, view = opened(run_world)
    request = control(view)
    reject(
        lambda: registry.checkpoint(**{**request, "expected_command_sequence": True}),
        "validation_error",
        422,
    )
    saved = registry.checkpoint(**request)
    snapshot = deepcopy(saved)
    object.__setattr__(saved.last_command, "action", "invalid")
    assert registry.checkpoint(**request) == snapshot
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE projects SET owner_id=:u WHERE id=:p"),
            {"u": run_world["owners"]["foreign"], "p": runtime.project_id},
        )
    reject(lambda: registry.checkpoint(**request), "not_found", 404)
    reject(lambda: registry.close(**control(snapshot), mode="release_local"), "not_found", 404)
