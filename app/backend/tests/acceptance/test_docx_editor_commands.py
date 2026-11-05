"""Frozen D03-16D2: ordered native editing with atomic RAM publication."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_docx_checkpoints import api as checkpoints
from test_docx_checkpoints import prepare, put, reject, working
from test_docx_editor_registry import api, opening
from test_docx_save_commit import prepared

from ara.docx_documents import get_docx, save_docx
from ara.docx_package.editor import (
    Caret,
    CaretTarget,
    EditorSelection,
    EditorSession,
    SelectionTarget,
)
from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.ranges import RangeEdit, TextPosition
from ara.docx_package.structure import InsertParagraph


def opened(world, **options):
    runtime, item, _ = prepare(world)
    registry = api().EditorRegistry(runtime, **options)
    view = registry.open(**opening(registry, item)).view
    return runtime, item, registry, view


def command(registry, view, action, value=None, after=None, **overrides):
    return {
        "document_id": view.document_id,
        "session_id": view.session_id,
        "command_id": uuid4(),
        "expected_command_sequence": view.command_sequence,
        "expected_session_revision": view.editor.document.revision,
        "command": api().EditorCommand(action, value, after),
        **overrides,
    }


def test_native_typing_replay_undo_redo_keep_exact_history(run_world):
    runtime, item, registry, view = opened(run_world)
    request = command(registry, view, "insert_text", "New 🧪 ")
    edited = registry.command(**request)
    assert edited.command_sequence == edited.editor.document.revision == 1
    assert edited.editor.document.is_dirty and edited.editor.document.undo_depth == 1
    assert edited.last_command.command_id == request["command_id"]
    assert edited.last_command.result_command_sequence == 1
    assert registry.command(**request) == edited
    undo = registry.command(**command(registry, edited, "undo"))
    assert undo.editor.document.data == item.current_data and not undo.editor.document.is_dirty
    redo = registry.command(**command(registry, undo, "redo"))
    assert redo.editor.document.data == edited.editor.document.data
    assert redo.editor.selection == edited.editor.selection and redo.command_sequence == 3
    reject(lambda: registry.command(**request), "stale_command")
    assert get_docx(runtime, document_id=item.document_id) == item
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.phase
        == "empty"
    )


def test_capture_noop_and_altered_latest_are_ordered(run_world):
    _, _, registry, view = opened(run_world)
    anchor = view.editor.selection.anchor.anchor
    caret = Caret(anchor, 2, "left")
    selection = EditorSelection(caret, caret)
    request = command(registry, view, "capture", selection)
    captured = registry.command(**request)
    assert captured.command_sequence == 1 and captured.editor.document.revision == 0
    assert captured.editor.selection == selection
    reject(
        lambda: registry.command(**{**request, "command": api().EditorCommand("insert_text", "X")}),
        "idempotency_conflict",
    )
    reject(
        lambda: registry.command(**{**request, "expected_command_sequence": 1}),
        "idempotency_conflict",
    )
    no_op = registry.command(**command(registry, captured, "insert_text", ""))
    assert no_op.command_sequence == 2 and no_op.editor.document.revision == 0
    assert no_op.editor.document.data == view.editor.document.data
    reject(
        lambda: registry.command(**command(registry, view, "capture", selection)), "stale_command"
    )


@pytest.mark.parametrize(
    "action",
    [
        "enter",
        "join_previous",
        "join_next",
        "paste_text",
        "insert_soft_break",
        "range_edit",
        "structure",
        "format",
    ],
)
def test_adapter_matches_exact_native_operation(run_world, action):
    _, _, registry, view = opened(run_world)
    native = EditorSession(view.editor.document.data)
    before = native.snapshot()
    after, value = None, None
    if action == "paste_text":
        value = "One\r\nTwo 🧪"
        expected = native.paste_text(value, expected_revision=0)
    elif action == "range_edit":
        span = next(s for s in before.document.projection.blocks[0].spans if s.kind == "text")
        value = (
            RangeEdit(TextPosition(span.anchor, 0), TextPosition(span.anchor, 6), "Device", "Item"),
        )
        target = CaretTarget(0, 4)
        after = SelectionTarget(target, target)
        expected = native.apply(value, after=after, expected_revision=0)
    elif action == "structure":
        paragraph = before.document.projection.blocks[0]
        value = (InsertParagraph(paragraph.anchor, paragraph.text, ("Next",)),)
        target = CaretTarget(0, 0)
        after = SelectionTarget(target, target)
        expected = native.apply_structure(value, after=after, expected_revision=0)
    elif action == "format":
        paragraph = before.document.projection.blocks[0]
        value = (ParagraphFormat(paragraph.anchor, paragraph.text),)
        expected = native.apply_formats(value, expected_revision=0)
    elif action == "join_next":
        caret = Caret(
            before.selection.anchor.anchor, len(before.document.projection.blocks[0].text)
        )
        selection = EditorSelection(caret, caret)
        view = registry.command(**command(registry, view, "capture", selection))
        native.capture(selection, expected_revision=0)
        expected = native.join_next(expected_revision=0)
    else:
        expected = getattr(native, action)(expected_revision=0)
    result = registry.command(**command(registry, view, action, value, after))
    assert result.editor == expected
    assert result.command_sequence == view.command_sequence + 1


def test_two_concurrent_commands_same_base_accept_exactly_one(run_world):
    _, _, registry, view = opened(run_world)
    barrier = Barrier(2)

    def call(label):
        from ara.documents.storage import DocumentError

        request = command(registry, view, "insert_text", label)
        barrier.wait(5)
        try:
            return registry.command(**request)
        except DocumentError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, ("One ", "Two ")))
    assert sorted(getattr(r, "code", "accepted") for r in results) == ["accepted", "stale_command"]
    assert (
        registry.snapshot(document_id=view.document_id, session_id=view.session_id).command_sequence
        == 1
    )


def test_native_failure_and_read_commit_failure_preserve_entire_actor(run_world, monkeypatch):
    runtime, _, registry, view = opened(run_world)
    reject(lambda: registry.command(**command(registry, view, "undo")), "nothing_to_undo", 422)
    request = command(registry, view, "insert_text", "New ")

    def fail(connection):
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: registry.command(**request), "storage_unavailable", 503)
    assert registry.snapshot(document_id=view.document_id, session_id=view.session_id) == view
    assert registry.command(**request).command_sequence == 1


def test_external_fence_scope_and_latest_replay_never_reapply(run_world):
    runtime, item, registry, view = opened(run_world)
    request = command(registry, view, "insert_text", "New ")
    edited = registry.command(**request)
    save_docx(
        runtime, document_id=item.document_id, expected_storage_revision=1, data=item.current_data
    )
    replay = registry.command(**request)
    assert replay.state == "conflict" and replay.editor == edited.editor
    reject(
        lambda: registry.command(**command(registry, edited, "insert_text", "More ")),
        "docx_conflict",
    )
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE projects SET owner_id=:u WHERE id=:p"),
            {"u": run_world["owners"]["foreign"], "p": runtime.project_id},
        )
    reject(lambda: registry.command(**request), "not_found", 404)


def test_pending_and_changed_checkpoint_reject_new_commands(run_world):
    runtime, item, pending = prepared(run_world)
    registry = api().EditorRegistry(runtime)
    view = registry.open(**opening(registry, item, mode="recover")).view
    reject(
        lambda: registry.command(**command(registry, view, "insert_text", "X")),
        "editor_operation_pending",
    )
    runtime2, item2, registry2, view2 = opened(run_world)
    put(runtime2, item2, **working(item2))
    reject(
        lambda: registry2.command(**command(registry2, view2, "insert_text", "X")),
        "checkpoint_conflict",
    )


def test_tampered_input_and_output_are_detached(run_world):
    _, _, registry, view = opened(run_world)
    request = command(registry, view, "capture", view.editor.selection)
    original = deepcopy(request)
    accepted = registry.command(**request)
    object.__setattr__(request["command"].value.focus, "offset", 999)
    object.__setattr__(accepted.editor.selection.focus, "offset", 999)
    assert registry.command(**original).editor.selection == view.editor.selection
    bad = deepcopy(original["command"])
    object.__setattr__(bad, "action", lambda: None)
    reject(lambda: registry.command(**{**original, "command": bad}), "validation_error", 422)
    assert not hasattr(registry.command(**original).last_command, "value")
