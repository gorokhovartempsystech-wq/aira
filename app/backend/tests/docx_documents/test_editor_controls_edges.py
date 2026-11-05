"""Pending proof, terminal release, stale actor races and ACK-loss recovery."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from functools import partial
from threading import Event, Lock, current_thread, main_thread

import pytest

from ara.docx_documents import get_docx, save_docx
from ara.docx_documents._dto import MAX_REVISION
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import api as checkpoints
from tests.acceptance.test_docx_checkpoints import put, reject, working
from tests.acceptance.test_docx_editor_commands import command, opened
from tests.acceptance.test_docx_editor_controls import control
from tests.acceptance.test_docx_editor_registry import opening
from tests.acceptance.test_docx_recovery import request as legacy_request
from tests.acceptance.test_docx_text_edit import client, seed


def freeze(registry, view, monkeypatch, *, committed=False):
    module = importlib.import_module("ara.docx_editor._controls")
    real = module.put_checkpoint
    seen = []
    request = control(view)

    def unknown(*args, **kwargs):
        actor = registry._actors[(view.document_id, view.session_id)]
        assert actor.state.active is not None
        seen.append(deepcopy(kwargs))
        if committed:
            real(*args, **kwargs)
        from ara.documents.storage import DocumentError

        raise DocumentError(503, "storage_unavailable", "Synthetic unknown outcome", True)

    with monkeypatch.context() as patch:
        patch.setattr(module, "put_checkpoint", unknown)
        reject(lambda: registry.checkpoint(**request), "storage_unavailable", 503)
    return request, seen[0]


def test_attempt_exists_before_dispatch_other_document_works_and_descriptor_detaches(
    run_world, monkeypatch
):
    runtime, item, registry, view = opened(run_world)
    native_request = command(registry, view, "insert_text", "Local ")
    view = registry.command(**native_request)
    request, original = freeze(registry, view, monkeypatch)
    frozen = registry.snapshot(document_id=view.document_id, session_id=view.session_id)
    assert registry.command(**native_request).editor == view.editor
    object.__setattr__(frozen.active_command, "stage", "invalid")
    assert (
        registry.snapshot(
            document_id=view.document_id, session_id=view.session_id
        ).active_command.stage
        == "checkpoint_pending"
    )
    second = seed(run_world)
    other = registry.open(**opening(registry, second)).view
    assert (
        registry.command(**command(registry, other, "insert_text", "Other ")).command_sequence == 1
    )
    module = importlib.import_module("ara.docx_editor._controls")
    real = module.put_checkpoint

    def repeated(*args, **kwargs):
        assert kwargs == original
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "put_checkpoint", repeated)
    result = registry.reconcile(**request)
    assert result.command_sequence == view.command_sequence + 1
    assert get_docx(runtime, document_id=item.document_id) == item


def test_foreign_empty_legacy_fence_still_allows_local_snapshot_and_release(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    freeze(registry, view, monkeypatch)
    with client(runtime) as http:
        response = http.put(
            f"/docx-documents/{item.document_id}/draft", json=legacy_request(http, item)
        )
        assert response.status_code == 200
    local = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert local.state == "conflict" and local.editor == view.editor
    registry.close(**control(local), mode="release_local")
    assert get_docx(runtime, document_id=item.document_id) == item


@pytest.mark.parametrize("foreign_head", [False, True])
def test_confirmed_put_then_foreign_change_never_acknowledges_old_target(
    run_world, monkeypatch, foreign_head
):
    runtime, item, registry, view = opened(run_world)
    view = registry.command(**command(registry, view, "insert_text", "Local "))
    request, _ = freeze(registry, view, monkeypatch, committed=True)
    if foreign_head:
        save_docx(
            runtime,
            document_id=item.document_id,
            expected_storage_revision=1,
            data=item.current_data,
        )
    else:
        put(runtime, item, expected=2, **working(item, "Other "))
    local = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert local.state == "conflict" and local.editor == view.editor
    reject(
        lambda: registry.reconcile(**request),
        "docx_conflict" if foreign_head else "checkpoint_conflict",
    )
    assert (
        registry.snapshot(document_id=item.document_id, session_id=view.session_id).command_sequence
        == view.command_sequence
    )
    before = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    registry.close(**control(local), mode="release_local")
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == before


def test_close_reply_failure_keeps_attempt_and_reconcile_removes_once(run_world, monkeypatch):
    runtime, item, registry, view = opened(run_world)
    request = control(view)
    model = importlib.import_module("ara.docx_editor._models")

    def fail(self):
        raise RuntimeError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(model.ClosedEditor, "__post_init__", fail)
        reject(lambda: registry.close(**request), "editor_error", 500)
    assert (
        registry.snapshot(document_id=item.document_id, session_id=view.session_id).state
        == "operation_pending"
    )
    assert registry.reconcile(**request).checkpoint_revision == 2
    reject(lambda: registry.reconcile(**request), "editor_session_expired", 410)
    assert (
        checkpoints()
        .get_checkpoint(runtime, document_id=item.document_id)
        .checkpoint.checkpoint_revision
        == 2
    )
    assert not registry._actors and not registry._opens and not registry._budget.groups


@pytest.mark.parametrize("operation", ["snapshot", "open", "command", "checkpoint"])
def test_waiting_stale_actor_cannot_return_after_close(run_world, operation):
    _, item, registry, view = opened(run_world)
    actor = registry._actors[(item.document_id, view.session_id)]
    entered, permit = Event(), Event()
    real = Lock()

    class Gate:
        def __enter__(self):
            if current_thread() is not main_thread():
                entered.set()
                assert permit.wait(5)
            real.acquire()

        def __exit__(self, *args):
            real.release()

    actor.mutex = Gate()
    if operation == "snapshot":
        call = partial(registry.snapshot, document_id=item.document_id, session_id=view.session_id)
    elif operation == "open":
        keys = (
            "document_id",
            "registry_id",
            "client_open_id",
            "expected_open_sequence",
            "expected_checkpoint_revision",
            "mode",
        )
        call = partial(registry.open, **dict(zip(keys, actor.request, strict=True)))
    elif operation == "command":
        request = command(registry, view, "insert_text", "Late ")
        call = partial(registry.command, **request)
    else:
        request = control(view)
        call = partial(registry.checkpoint, **request)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(call)
        assert entered.wait(5)
        try:
            registry.close(**control(view), mode="release_local")
        finally:
            permit.set()
        reject(lambda: future.result(10), "editor_session_expired", 410)
    assert not registry._actors and not registry._budget.groups


def test_exhaustion_before_dispatch_and_release_exception(run_world):
    runtime, item, registry, view = opened(run_world)
    actor = registry._actors[(item.document_id, view.session_id)]
    actor.state = replace(actor.state, command_sequence=MAX_REVISION)
    current = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    reject(lambda: registry.checkpoint(**control(current)), "revision_exhausted")
    assert actor.state.active is None
    registry.close(**control(current), mode="release_local")
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.phase
        == "empty"
    )


def test_active_identity_and_release_intent_must_be_distinct(run_world, monkeypatch):
    _, item, registry, view = opened(run_world)
    request, _ = freeze(registry, view, monkeypatch)
    reject(lambda: registry.save(**request), "idempotency_conflict")
    reject(lambda: registry.close(**request, mode="release_local"), "idempotency_conflict")
    reject(
        lambda: registry.reconcile(**{**request, "expected_command_sequence": 1}),
        "idempotency_conflict",
    )
    assert registry.reconcile(**request).command_sequence == 1
    reject(lambda: registry.reconcile(**control(view)), "editor_operation_missing")
