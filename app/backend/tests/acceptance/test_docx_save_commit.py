"""Frozen D03-16C2: atomic current+receipt and superseded replay safety."""

import importlib
from copy import deepcopy

import pytest
from sqlalchemy import event, text
from test_docx_checkpoints import api as checkpoints
from test_docx_checkpoints import prepare, reject, working
from test_docx_recovery import path, request
from test_docx_save_prepare import prepare_save
from test_docx_text_edit import client

from ara.docx_documents import get_docx, save_docx


def api():
    return importlib.import_module("ara.docx_documents.save_commit")


def prepared(world):
    runtime, item, _ = prepare(world)
    value = prepare_save(runtime, item, **working(item))
    return runtime, item, value


def test_commit_writes_current_and_receipt_once_but_leaves_pending_exact(run_world):
    runtime, item, pending = prepared(run_world)
    result = api().commit_save(runtime, handle=pending.handle)
    assert result.receipt.storage_revision == item.storage_revision + 1
    assert result.receipt.current_sha256 == pending.handle.working_sha256
    assert result.receipt.current_size_bytes == pending.handle.working_size_bytes
    assert result.document.current_data == pending.snapshot.checkpoint.working_data
    assert result.document.original_data == item.original_data and result.current_matches_receipt
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == pending.snapshot.checkpoint
    )
    assert api().commit_save(runtime, handle=pending.handle) == result
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1


def test_old_replay_ignores_newer_head_checkpoint_and_legacy_draft(run_world, monkeypatch):
    runtime, item, pending = prepared(run_world)
    saved = api().commit_save(runtime, handle=pending.handle)
    latest = save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=saved.document.storage_revision,
        data=saved.document.current_data,
    )
    with runtime.engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE docx_editor_checkpoints SET phase='empty',checkpoint_revision=3,
            base_storage_revision=NULL,base_sha256=NULL,working_data=NULL,
            working_sha256=NULL,metadata=NULL,last_request_id=NULL,last_request_sha256=NULL
        """)
        )
    with client(runtime) as http:
        body = request(http, latest)
        assert http.put(path(latest), json=body).status_code == 200

    def forbidden(*args, **kwargs):
        raise AssertionError("Receipt replay must not inspect checkpoints")

    with monkeypatch.context() as patch:
        patch.setattr(checkpoints(), "_record", forbidden)
        replay = api().commit_save(runtime, handle=pending.handle)
    assert replay.receipt == saved.receipt and replay.document == latest
    assert not replay.current_matches_receipt
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_drafts")) == 1
        assert conn.scalar(text("SELECT checkpoint_revision FROM docx_editor_checkpoints")) == 4


def test_foreign_writer_blocks_first_commit_without_clearing_pending(run_world):
    runtime, item, pending = prepared(run_world)
    latest = save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=item.storage_revision,
        data=item.current_data,
    )
    reject(lambda: api().commit_save(runtime, handle=pending.handle), "docx_conflict")
    snapshot = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    assert snapshot.document == latest and snapshot.checkpoint == pending.snapshot.checkpoint
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0


def test_scope_precedes_receipt_replay_and_altered_handle_is_not_accepted(run_world):
    runtime, item, pending = prepared(run_world)
    api().commit_save(runtime, handle=pending.handle)
    reject(
        lambda: api().commit_save(run_world["runtimes"]["foreign"], handle=pending.handle),
        "not_found",
        404,
    )
    damaged = deepcopy(pending.handle)
    object.__setattr__(damaged, "prepared_checkpoint_revision", 99)
    reject(lambda: api().commit_save(runtime, handle=damaged), "validation_error", 422)
    assert (
        get_docx(runtime, document_id=item.document_id).storage_revision
        == item.storage_revision + 1
    )


@pytest.mark.parametrize("fault", ["reply", "receipt_insert"])
def test_failed_response_or_receipt_insert_rolls_back_document(run_world, monkeypatch, fault):
    runtime, item, pending = prepared(run_world)
    api()
    model = importlib.import_module("ara.docx_documents.save_models")

    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE")

    def before(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO DOCX_EDIT_RECEIPTS"):
            fail()

    with monkeypatch.context() as patch:
        if fault == "reply":
            patch.setattr(model.CommittedSave, "__init__", fail)
        else:
            event.listen(runtime.engine, "before_cursor_execute", before)
        try:
            reject(lambda: api().commit_save(runtime, handle=pending.handle), "storage_error", 500)
        finally:
            if fault == "receipt_insert":
                event.remove(runtime.engine, "before_cursor_execute", before)
    assert get_docx(runtime, document_id=item.document_id) == item
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == pending.snapshot.checkpoint
    )
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0


def test_matching_hash_without_durable_pending_never_creates_a_save(run_world):
    runtime, item, pending = prepared(run_world)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE docx_editor_checkpoints SET phase='empty',checkpoint_revision=3,
            base_storage_revision=NULL,base_sha256=NULL,working_data=NULL,
            working_sha256=NULL,metadata=NULL,last_request_id=NULL,last_request_sha256=NULL
        """)
        )
    reject(lambda: api().commit_save(runtime, handle=pending.handle), "checkpoint_conflict")
    assert get_docx(runtime, document_id=item.document_id) == item


def test_corrupt_receipt_cannot_match_another_revision_after_newer_save(run_world):
    runtime, item, pending = prepared(run_world)
    saved = api().commit_save(runtime, handle=pending.handle)
    save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=saved.receipt.storage_revision,
        data=saved.document.current_data,
    )
    with runtime.engine.begin() as conn:
        conn.execute(text("UPDATE docx_edit_receipts SET storage_revision=3"))
    reject(lambda: api().commit_save(runtime, handle=pending.handle), "storage_error", 500)
