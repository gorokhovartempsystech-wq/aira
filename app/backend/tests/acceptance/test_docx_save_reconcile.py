"""Frozen C3B: explicit discard and restartable commit/finalize composition."""

import importlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_checkpoints import api as checkpoints
from test_docx_checkpoints import put, reject, working
from test_docx_save_commit import prepared

from ara.documents.storage import DocumentError
from ara.docx_documents import get_docx, save_docx
from ara.docx_documents.save_commit import commit_save
from ara.docx_documents.save_finalize import finalize_save


def api():
    return importlib.import_module("ara.docx_documents.save_reconcile")


def test_explicit_unconfirmed_discard_keeps_current_and_fences_late_commit(run_world):
    runtime, item, pending = prepared(run_world)
    key = uuid4()
    result = api().discard_pending(runtime, handle=pending.handle, request_id=key)
    c = result.snapshot.checkpoint
    assert c.phase == "empty" and c.checkpoint_revision == 3 and c.working_data is None
    assert c.metadata is None and c.base_storage_revision is None
    assert (
        result.receipt is None and not result.save_confirmed and not result.current_matches_receipt
    )
    assert result.snapshot.document == item
    assert api().discard_pending(runtime, handle=pending.handle, request_id=key) == result
    assert api().discard_pending(runtime, handle=pending.handle, request_id=uuid4()) == result
    reject(lambda: commit_save(runtime, handle=pending.handle), "checkpoint_conflict")
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT metadata IS NULL FROM docx_editor_checkpoints"))
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0


@pytest.mark.parametrize("newer", [False, True])
def test_discard_never_undoes_confirmed_current_or_newer_head(run_world, newer):
    runtime, item, pending = prepared(run_world)
    saved = commit_save(runtime, handle=pending.handle)
    head = saved.document
    if newer:
        head = save_docx(
            runtime,
            document_id=item.document_id,
            expected_storage_revision=head.storage_revision,
            data=head.current_data,
        )
    result = api().discard_pending(runtime, handle=pending.handle, request_id=uuid4())
    assert result.save_confirmed and result.receipt == saved.receipt
    assert result.current_matches_receipt == (not newer)
    assert result.snapshot.document == head
    assert commit_save(runtime, handle=pending.handle).receipt == saved.receipt
    assert get_docx(runtime, document_id=item.document_id) == head


def test_superseded_and_finalized_copies_are_not_discarded(run_world):
    runtime, item, pending = prepared(run_world)
    result = api().discard_pending(runtime, handle=pending.handle, request_id=uuid4())
    newer = put(runtime, item, expected=3, **working(item, "New "))
    reject(
        lambda: api().discard_pending(runtime, handle=pending.handle, request_id=uuid4()),
        "checkpoint_conflict",
    )
    reject(
        lambda: api().reconcile_save(runtime, handle=pending.handle, request_id=uuid4()),
        "checkpoint_conflict",
    )
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == newer
    assert result.snapshot.checkpoint.checkpoint_revision == 3


def test_discard_does_not_accept_finalize_action_proof(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    key = uuid4()
    result = finalize_save(runtime, handle=pending.handle, request_id=key)
    reject(
        lambda: api().discard_pending(runtime, handle=pending.handle, request_id=key),
        "idempotency_conflict",
    )
    reject(
        lambda: api().discard_pending(runtime, handle=pending.handle, request_id=uuid4()),
        "checkpoint_conflict",
    )
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == result.snapshot


def test_reconcile_saves_and_finalizes_once_for_the_same_operation(run_world):
    runtime, item, pending = prepared(run_world)
    key = uuid4()
    result = api().reconcile_save(runtime, handle=pending.handle, request_id=key)
    assert (
        result.receipt.storage_revision == 2 and result.snapshot.checkpoint.checkpoint_revision == 3
    )
    assert result.current_matches_receipt and result.snapshot.checkpoint.metadata.pending is None
    assert api().reconcile_save(runtime, handle=pending.handle, request_id=key) == result
    assert api().reconcile_save(runtime, handle=pending.handle, request_id=uuid4()) == result
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1


def test_invalid_reconcile_request_id_is_rejected_before_current_is_saved(run_world):
    runtime, item, pending = prepared(run_world)
    reject(
        lambda: api().reconcile_save(runtime, handle=pending.handle, request_id=True),
        "validation_error",
        422,
    )
    assert get_docx(runtime, document_id=item.document_id) == item
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == pending.snapshot


def test_failure_between_commit_and_finalize_is_recoverable(run_world, monkeypatch):
    runtime, item, pending = prepared(run_world)
    key = uuid4()

    def fail(*args, **kwargs):
        raise DocumentError(503, "storage_unavailable", "Unavailable", True)

    with monkeypatch.context() as patch:
        patch.setattr(api(), "finalize_save", fail)
        reject(
            lambda: api().reconcile_save(runtime, handle=pending.handle, request_id=key),
            "storage_unavailable",
            503,
        )
    current = get_docx(runtime, document_id=item.document_id)
    assert current.storage_revision == 2 and current.current_sha256 == pending.handle.working_sha256
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == pending.snapshot.checkpoint
    )
    result = api().reconcile_save(runtime, handle=pending.handle, request_id=key)
    assert (
        result.snapshot.checkpoint.checkpoint_revision == 3 and result.receipt.storage_revision == 2
    )


def test_corrupt_receipt_refuses_discard_without_destroying_work(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    with runtime.engine.begin() as conn:
        conn.execute(text("UPDATE docx_edit_receipts SET current_size_bytes=current_size_bytes+1"))
    reject(
        lambda: api().discard_pending(runtime, handle=pending.handle, request_id=uuid4()),
        "storage_error",
        500,
    )
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == pending.snapshot.checkpoint
    )
