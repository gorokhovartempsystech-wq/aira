"""Frozen D03-16C1: durable pending bytes and a complete immutable save identity."""

import importlib
import json
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_checkpoints import api as checkpoints
from test_docx_checkpoints import prepare, put, reject, working
from test_docx_recovery import request
from test_docx_text_edit import client

from ara.docx_documents import get_docx, save_docx
from ara.docx_package.checkpoint import encode_metadata


def api():
    return importlib.import_module("ara.docx_documents.save_prepare")


def prepare_save(runtime, item, expected=1, request_id=None, operation_id=None, **values):
    return api().prepare_save(
        runtime,
        document_id=item.document_id,
        expected_checkpoint_revision=expected,
        request_id=request_id or uuid4(),
        operation_id=operation_id or uuid4(),
        **values,
    )


@pytest.mark.parametrize("existing", [False, True])
def test_prepare_persists_exact_pending_but_does_not_save_current(run_world, existing):
    runtime, item, _ = prepare(run_world)
    values = working(item)
    if existing:
        put(runtime, item, **values)
    prepared = prepare_save(runtime, item, expected=2 if existing else 1, **values)
    c, h = prepared.snapshot.checkpoint, prepared.handle
    assert c.phase == "pending" and c.checkpoint_revision == (3 if existing else 2)
    assert c.working_data == values["data"] and c.metadata.selection == values["metadata"].selection
    assert (
        h.document_id == item.document_id
        and h.prepared_checkpoint_revision == c.checkpoint_revision
    )
    assert h.working_sha256 == sha256(values["data"]).hexdigest()
    assert h.working_size_bytes == len(values["data"])
    assert h.metadata == c.metadata and h.operation_id == c.metadata.pending.operation_id
    assert get_docx(runtime, document_id=item.document_id) == item
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == prepared.snapshot
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0


def test_prepare_replay_altered_request_and_another_pending_are_distinct(run_world):
    runtime, item, _ = prepare(run_world)
    values, key, operation = working(item), uuid4(), uuid4()
    saved = prepare_save(runtime, item, request_id=key, operation_id=operation, **values)
    assert prepare_save(runtime, item, request_id=key, operation_id=operation, **values) == saved
    reject(
        lambda: prepare_save(runtime, item, request_id=key, operation_id=uuid4(), **values),
        "idempotency_conflict",
    )
    reject(lambda: prepare_save(runtime, item, expected=2, **values), "pending_save_required")
    # A later empty tombstone stands in for the separately delivered discard_pending lifecycle.
    with runtime.engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE docx_editor_checkpoints SET phase='empty',checkpoint_revision=3,
            base_storage_revision=NULL,base_sha256=NULL,working_data=NULL,
            working_sha256=NULL,metadata=NULL,last_request_id=:r,last_request_sha256=:h
        """),
            {"r": uuid4(), "h": "f" * 64},
        )
    reject(
        lambda: prepare_save(runtime, item, request_id=key, operation_id=operation, **values),
        "checkpoint_conflict",
    )


def test_handle_matches_canonical_recipe_without_retaining_docx_bytes(run_world):
    runtime, item, _ = prepare(run_world)
    prepared = prepare_save(runtime, item, **working(item))
    h = prepared.handle
    wire = encode_metadata(
        h.metadata,
        data=prepared.snapshot.checkpoint.working_data,
        saved_sha256=h.base_sha256,
        phase="pending",
    )
    identity = {
        "version": 1,
        "document_id": str(h.document_id),
        "operation_id": str(h.operation_id),
        "prepared_checkpoint_revision": str(h.prepared_checkpoint_revision),
        "base_storage_revision": str(h.base_storage_revision),
        "base_sha256": h.base_sha256,
        "working_sha256": h.working_sha256,
        "working_size_bytes": h.working_size_bytes,
        "origin": wire["origin"],
        "selection": wire["selection"],
    }
    expected = sha256(
        b"ara.docx.editor-save.v1\0"
        + json.dumps(identity, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert h.request_sha256 == expected
    assert not hasattr(h, "working_data") and not hasattr(h, "data")
    proof = deepcopy(h)
    object.__setattr__(
        proof, "prepared_checkpoint_revision", proof.prepared_checkpoint_revision + 1
    )
    with pytest.raises(ValueError):
        proof.__post_init__()
    proof = deepcopy(h)
    object.__setattr__(proof.metadata.origin, "session_revision", 99)
    with pytest.raises(ValueError):
        proof.__post_init__()


def test_old_receipt_key_cannot_create_a_new_pending_save(run_world):
    runtime, item, _ = prepare(run_world)
    operation = uuid4()
    with client(runtime) as http:
        body = request(http, item)["edit"]
        response = http.post(
            f"/docx-documents/{item.document_id}/text-edit",
            json=body,
            headers={"Idempotency-Key": str(operation)},
        )
        assert response.status_code == 200
    current = get_docx(runtime, document_id=item.document_id)
    reject(
        lambda: prepare_save(runtime, current, operation_id=operation, **working(current)),
        "idempotency_conflict",
    )
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.phase
        == "empty"
    )


def test_prepare_scope_and_stale_base_do_not_replace_checkpoint(run_world):
    runtime, item, empty = prepare(run_world)
    values = working(item)
    reject(lambda: prepare_save(run_world["runtimes"]["foreign"], item, **values), "not_found", 404)
    save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=item.storage_revision,
        data=item.current_data,
    )
    reject(lambda: prepare_save(runtime, item, **values), "docx_conflict")
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == empty.checkpoint
    )


def test_prepare_reply_failure_rolls_back_and_handle_does_not_alias_snapshot(
    run_world, monkeypatch
):
    runtime, item, empty = prepare(run_world)
    api()
    models = importlib.import_module("ara.docx_documents.save_models")
    values = working(item)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic response failure")

    with monkeypatch.context() as patch:
        patch.setattr(models.PreparedSave, "__init__", fail)
        reject(lambda: prepare_save(runtime, item, **values), "storage_error", 500)
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == empty
    saved = prepare_save(runtime, item, **values)
    original = deepcopy(saved.snapshot.checkpoint.metadata)
    object.__setattr__(saved.handle.metadata.origin, "position_id", 999)
    assert saved.snapshot.checkpoint.metadata == original
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.metadata
        == original
    )
