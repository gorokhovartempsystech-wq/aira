"""Frozen D03-16D1: scoped opening and exact restart recovery, without writes."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from test_docx_checkpoints import api as checkpoints
from test_docx_checkpoints import prepare, put, reject, working
from test_docx_save_commit import prepared
from test_docx_text_edit import seed

from ara.docx_documents import get_docx, save_docx
from ara.docx_documents.save_commit import commit_save


def api():
    return importlib.import_module("ara.docx_editor")


def opening(registry, item, **overrides):
    observed = registry.inspect_recovery(document_id=item.document_id)
    return {
        "document_id": item.document_id,
        "registry_id": observed.registry_id,
        "client_open_id": uuid4(),
        "expected_open_sequence": observed.open_sequence,
        "expected_checkpoint_revision": observed.checkpoint_revision,
        "mode": "current",
        **overrides,
    }


def test_passive_inspect_and_current_open_replay(run_world):
    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    registry = api().EditorRegistry(runtime)
    observed = registry.inspect_recovery(document_id=item.document_id)
    assert observed.phase == "absent" and observed.checkpoint_revision == 0
    assert observed.open_sequence == 0 and not hasattr(observed, "data")
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_editor_checkpoints")) == 0
    request = opening(registry, item)
    result = registry.open(**request)
    view = result.view
    assert result.accepted_open_sequence == 0 and result.next_open_sequence == 1
    assert view.editor.document.data == item.current_data and not view.editor.document.is_dirty
    assert view.command_sequence == view.editor.document.revision == view.editor.position_id == 0
    assert view.editor.document.undo_depth == view.editor.document.redo_depth == 0
    assert view.state == "editable" and view.checkpoint_revision == 1
    assert registry.open(**request) == result
    other = registry.open(**opening(registry, item))
    assert other.view.session_id != view.session_id and other.next_open_sequence == 2
    assert registry.open(**request).view == view
    assert get_docx(runtime, document_id=item.document_id) == item


@pytest.mark.parametrize("dirty", [False, True])
def test_working_restore_has_new_epoch_exact_selection_and_empty_history(run_world, dirty):
    runtime, item, _ = prepare(run_world)
    values = working(item, "Changed " if dirty else "")
    metadata = values["metadata"]
    saved = put(runtime, item, **values)
    registry = api().EditorRegistry(runtime)
    result = registry.open(**opening(registry, item, mode="recover"))
    view = result.view
    assert view.editor.document.data == values["data"]
    assert view.editor.selection == metadata.selection
    assert view.editor.document.is_dirty is dirty
    assert view.editor.document.revision == view.editor.position_id == 0
    assert view.editor.document.undo_depth == view.editor.document.redo_depth == 0
    assert view.session_id != metadata.origin.session_id
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == saved
    reject(lambda: registry.open(**opening(registry, item)), "checkpoint_conflict")


def test_foreign_base_and_same_bytes_are_conflict_without_losing_copy(run_world):
    runtime, item, _ = prepare(run_world)
    values = working(item)
    put(runtime, item, **values)
    newer = save_docx(
        runtime, document_id=item.document_id, expected_storage_revision=1, data=item.current_data
    )
    registry = api().EditorRegistry(runtime)
    view = registry.open(**opening(registry, item, mode="recover")).view
    assert view.state == "conflict" and view.base_storage_revision == 1
    assert view.observed_current.storage_revision == newer.storage_revision == 2
    assert view.editor.document.data == values["data"]


@pytest.mark.parametrize("committed", [False, True])
def test_pending_open_is_frozen_and_never_commits_or_finalizes(run_world, committed):
    runtime, item, pending = prepared(run_world)
    if committed:
        commit_save(runtime, handle=pending.handle)
    before = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    registry = api().EditorRegistry(runtime)
    observed = registry.inspect_recovery(document_id=item.document_id)
    assert observed.pending_status == ("committed" if committed else "ready")
    view = registry.open(**opening(registry, item, mode="recover")).view
    assert view.state == "recovery_pending" and view.editor.document.is_dirty
    assert view.recovery_operation_id == pending.handle.operation_id
    assert view.editor.document.data == pending.snapshot.checkpoint.working_data
    assert registry.snapshot(document_id=item.document_id, session_id=view.session_id) == view
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == before


def test_pending_corrupt_receipt_is_not_cleared(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    with runtime.engine.begin() as conn:
        conn.execute(text("UPDATE docx_edit_receipts SET current_size_bytes=current_size_bytes+1"))
    registry = api().EditorRegistry(runtime)
    reject(lambda: registry.inspect_recovery(document_id=item.document_id), "storage_error", 500)
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT phase FROM docx_editor_checkpoints")) == "pending"


def test_restart_and_scope_before_expired_or_idempotency(run_world):
    runtime, item, _ = prepare(run_world)
    first, second = api().EditorRegistry(runtime), api().EditorRegistry(runtime)
    request = opening(first, item)
    view = first.open(**request).view
    reject(lambda: second.open(**request), "editor_registry_expired", 410)
    reject(
        lambda: second.snapshot(document_id=item.document_id, session_id=view.session_id),
        "editor_session_expired",
        410,
    )
    foreign = api().EditorRegistry(run_world["runtimes"]["foreign"])
    reject(lambda: foreign.open(**request), "not_found", 404)
    reject(
        lambda: foreign.snapshot(document_id=item.document_id, session_id=view.session_id),
        "not_found",
        404,
    )
    assert second.open(**opening(second, item)).view.session_id != view.session_id
    reject(lambda: first.open(**{**request, "mode": "recover"}), "idempotency_conflict")
    reject(lambda: first.open(**{**request, "expected_open_sequence": 1}), "idempotency_conflict")
    reject(lambda: first.open(**{**request, "client_open_id": uuid4()}), "stale_open")


@pytest.mark.parametrize("same_id", [False, True])
def test_concurrent_open_publishes_only_one_increment(run_world, same_id):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    barrier = Barrier(2)

    def call(index):
        from ara.documents.storage import DocumentError

        barrier.wait(timeout=5)
        try:
            return registry.open(
                **{
                    **request,
                    "client_open_id": request["client_open_id"]
                    if same_id or index == 0
                    else uuid4(),
                }
            )
        except DocumentError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, (0, 1)))
    if same_id:
        assert results[0] == results[1]
    else:
        assert sorted(getattr(r, "code", "accepted") for r in results) == ["accepted", "stale_open"]
    assert registry.inspect_recovery(document_id=item.document_id).open_sequence == 1


def test_cached_scope_reads_no_blob_and_detects_revocation(run_world):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    view = registry.open(**request).view
    statements = []

    def trace(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(runtime.engine, "before_cursor_execute", trace)
    try:
        registry.snapshot(document_id=item.document_id, session_id=view.session_id)
        registry.open(**request)
    finally:
        event.remove(runtime.engine, "before_cursor_execute", trace)
    assert statements and all("original_data" not in s for s in statements)
    assert all("docx_documents.current_data" not in s or "octet_length" in s for s in statements)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE projects SET owner_id=:owner WHERE id=:id"),
            {"owner": run_world["owners"]["foreign"], "id": runtime.project_id},
        )
    reject(
        lambda: registry.snapshot(document_id=item.document_id, session_id=view.session_id),
        "not_found",
        404,
    )
    reject(lambda: registry.open(**request), "not_found", 404)


def test_admission_boundaries_and_failed_reply_do_not_consume_open(run_world, monkeypatch):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(
        runtime,
        limits=api().RegistryLimits(max_sessions=1, max_retained_bytes=len(item.current_data)),
    )
    request = opening(registry, item)
    model = importlib.import_module("ara.docx_editor._models")

    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(model.OpenedEditor, "__post_init__", fail)
        reject(lambda: registry.open(**request), "editor_error", 500)
    assert registry.inspect_recovery(document_id=item.document_id).open_sequence == 0
    view = registry.open(**request).view
    reject(lambda: registry.open(**opening(registry, item)), "editor_limit_exceeded", 413)
    assert registry.open(**request).view == view
    small = api().EditorRegistry(runtime, limits=api().RegistryLimits(max_retained_bytes=1))
    reject(lambda: small.open(**opening(small, item)), "editor_limit_exceeded", 413)
    assert small.inspect_recovery(document_id=item.document_id).open_sequence == 0


def test_read_commit_failure_and_output_mutation_cannot_publish_or_change_authority(
    run_world, monkeypatch
):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)

    def fail(connection):
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: registry.open(**request), "storage_unavailable", 503)
    result = registry.open(**request)
    baseline = deepcopy(result)
    object.__setattr__(result.view.editor.selection.focus, "offset", 999)
    object.__setattr__(result.view.observed_current, "title", "SYNTHETIC_PRIVATE")
    assert registry.open(**request) == baseline
    # Constructor context is an owned copy rather than caller-mutable authority.
    object.__setattr__(runtime, "project_id", run_world["projects"]["foreign"])
    assert registry.open(**request) == baseline


@pytest.mark.parametrize("value", [True, -1, 2**63, "0"])
def test_strict_open_counter_validation(run_world, value):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    reject(
        lambda: registry.open(**opening(registry, item, expected_open_sequence=value)),
        "validation_error",
        422,
    )


def test_limits_and_counter_overflow_revalidation(run_world):
    from ara.documents.storage import DocumentError

    runtime, item, _ = prepare(run_world)
    for value in (True, 0, -1):
        with pytest.raises((ValueError, DocumentError)):
            api().RegistryLimits(max_sessions=value)
    limit = api().RegistryLimits()
    object.__setattr__(limit, "max_retained_bytes", False)
    reject(lambda: api().EditorRegistry(runtime, limits=limit), "validation_error", 422)
    damaged = replace(runtime)
    object.__setattr__(damaged, "user_id", "invalid")
    reject(lambda: api().EditorRegistry(damaged), "validation_error", 422)
