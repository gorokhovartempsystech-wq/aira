"""Frozen C3A: confirmed cleanup, status and a reserved final CAS transition."""

import importlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_checkpoints import api as checkpoints
from test_docx_checkpoints import prepare, put, reject, working
from test_docx_save_commit import prepared
from test_docx_save_prepare import prepare_save

from ara.docx_documents import save_docx
from ara.docx_documents.checkpoint_fingerprints import pending_fingerprint
from ara.docx_documents.save_commit import commit_save
from ara.docx_documents.save_prepare import _prepared
from ara.docx_package.checkpoint import encode_metadata
from ara.docx_package.editor import EditorSession

MAX = 9223372036854775807


def api():
    return importlib.import_module("ara.docx_documents.save_finalize")


def test_status_and_finalize_preserve_bytes_selection_and_restore_clean(run_world):
    runtime, item, pending = prepared(run_world)
    status = api().get_save_status(runtime, handle=pending.handle)
    assert status.state == "ready" and status.receipt is None and status.checkpoint_revision == 2
    saved = commit_save(runtime, handle=pending.handle)
    status = api().get_save_status(runtime, handle=pending.handle)
    assert status.state == "committed" and status.receipt == saved.receipt
    assert status.checkpoint_revision is None
    result = api().finalize_save(runtime, handle=pending.handle, request_id=uuid4())
    c = result.snapshot.checkpoint
    assert c.phase == "working" and c.checkpoint_revision == 3
    assert (
        c.base_storage_revision == saved.receipt.storage_revision
        and c.base_sha256 == pending.handle.working_sha256
    )
    assert c.working_data == pending.snapshot.checkpoint.working_data and c.metadata.pending is None
    assert (
        c.metadata.selection == pending.handle.metadata.selection
        and c.metadata.origin == pending.handle.metadata.origin
    )
    assert result.receipt == saved.receipt and result.current_matches_receipt
    restored = EditorSession.restore(
        c.working_data, saved_sha256=c.base_sha256, selection=c.metadata.selection
    )
    assert not restored.snapshot().document.is_dirty
    assert restored.snapshot().document.undo_depth == 0
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1
        assert (
            conn.scalar(
                text("SELECT storage_revision FROM docx_documents WHERE id=:id"),
                {"id": item.document_id},
            )
            == 2
        )


def test_finalize_before_confirmation_does_not_remove_pending(run_world):
    runtime, item, pending = prepared(run_world)
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=uuid4()),
        "save_unconfirmed",
    )
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == pending.snapshot


@pytest.mark.parametrize("committed", [False, True])
def test_foreign_head_is_not_guessed_from_equal_bytes(run_world, committed):
    runtime, item, pending = prepared(run_world)
    head = commit_save(runtime, handle=pending.handle).document if committed else item
    save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=head.storage_revision,
        data=head.current_data,
    )
    status = api().get_save_status(runtime, handle=pending.handle)
    assert status.state == ("committed_outdated" if committed else "conflict")
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=uuid4()),
        "docx_conflict" if committed else "save_unconfirmed",
    )
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == pending.snapshot.checkpoint
    )


def test_repeated_and_independently_recovered_finalize_do_not_increment_again(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    request = uuid4()
    saved = api().finalize_save(runtime, handle=pending.handle, request_id=request)
    assert api().finalize_save(runtime, handle=pending.handle, request_id=request) == saved
    assert api().finalize_save(runtime, handle=pending.handle, request_id=uuid4()) == saved
    save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=2,
        data=saved.snapshot.document.current_data,
    )
    replay = api().finalize_save(runtime, handle=pending.handle, request_id=request)
    assert (
        replay.snapshot.checkpoint == saved.snapshot.checkpoint
        and not replay.current_matches_receipt
    )


def test_superseded_checkpoint_is_not_cleared_by_old_finalize(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    request = uuid4()
    finalized = api().finalize_save(runtime, handle=pending.handle, request_id=request)
    newer = put(
        runtime,
        finalized.snapshot.document,
        expected=3,
        **working(finalized.snapshot.document, "New "),
    )
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=request),
        "checkpoint_conflict",
    )
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == newer


def test_finalize_response_failure_rolls_back_only_cleanup(run_world, monkeypatch):
    runtime, item, pending = prepared(run_world)
    saved = commit_save(runtime, handle=pending.handle)
    api()
    models = importlib.import_module("ara.docx_documents.save_models")

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic response failure")

    with monkeypatch.context() as patch:
        patch.setattr(models.FinalizedSave, "__init__", fail)
        reject(
            lambda: api().finalize_save(runtime, handle=pending.handle, request_id=uuid4()),
            "storage_error",
            500,
        )
    snapshot = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    assert (
        snapshot.checkpoint == pending.snapshot.checkpoint and snapshot.document == saved.document
    )


def test_prepare_reserves_last_revision_and_final_cleanup_can_use_it(run_world):
    runtime, item, _ = prepare(run_world)
    values = working(item)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_editor_checkpoints SET checkpoint_revision=:r"), {"r": MAX - 1}
        )
    reject(lambda: prepare_save(runtime, item, expected=MAX - 1, **values), "revision_exhausted")
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.phase
        == "empty"
    )
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_editor_checkpoints SET checkpoint_revision=:r"), {"r": MAX - 2}
        )
    pending = prepare_save(runtime, item, expected=MAX - 2, **values)
    commit_save(runtime, handle=pending.handle)
    key = uuid4()
    saved = api().finalize_save(runtime, handle=pending.handle, request_id=key)
    assert saved.snapshot.checkpoint.checkpoint_revision == MAX
    assert api().finalize_save(runtime, handle=pending.handle, request_id=key) == saved


def test_preexisting_exhausted_pending_is_readable_but_cannot_be_freshly_committed(run_world):
    runtime, item, pending = prepared(run_world)
    c = pending.snapshot.checkpoint
    wire = encode_metadata(
        c.metadata, data=c.working_data, saved_sha256=c.base_sha256, phase="pending"
    )
    wire["pending"]["request_sha256"] = pending_fingerprint(
        item.document_id, MAX, c.base_storage_revision, c.base_sha256, c.working_data, wire
    )
    with runtime.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE docx_editor_checkpoints "
                "SET checkpoint_revision=:r,metadata=CAST(:m AS jsonb)"
            ),
            {"r": MAX, "m": json.dumps(wire)},
        )
    legacy = _prepared(checkpoints().get_checkpoint(runtime, document_id=item.document_id))
    assert api().get_save_status(runtime, handle=legacy.handle).state == "exhausted"
    reject(lambda: commit_save(runtime, handle=legacy.handle), "revision_exhausted")


def test_scope_and_request_identity_are_checked_before_cleanup(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    reject(
        lambda: api().finalize_save(
            run_world["runtimes"]["foreign"], handle=pending.handle, request_id=uuid4()
        ),
        "not_found",
        404,
    )
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=True),
        "validation_error",
        422,
    )
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == pending.snapshot.checkpoint
    )
