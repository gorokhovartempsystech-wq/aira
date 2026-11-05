"""Persist immutable pending work before any current-package save is attempted."""

from copy import deepcopy
from hashlib import sha256
from uuid import UUID

from ._dto import MAX_REVISION, _hash, valid_integer
from .checkpoint_fingerprints import checkpoint_fingerprint, pending_fingerprint
from .checkpoints import _conflict, _identity, _reply, _scope, _transition, _validate


def _prepared(snapshot):
    from .save_models import PreparedSave, SaveHandle

    c = snapshot.checkpoint
    handle = SaveHandle(
        c.document_id,
        c.checkpoint_revision,
        c.base_storage_revision,
        c.base_sha256,
        c.working_sha256,
        len(c.working_data),
        deepcopy(c.metadata),
    )
    return PreparedSave(snapshot, handle)


def prepare_save(
    runtime,
    *,
    document_id,
    expected_checkpoint_revision,
    request_id,
    operation_id,
    base_storage_revision,
    base_sha256,
    data,
    metadata,
):
    from ara.documents.storage import DocumentError, _session
    from ara.docx_package import DocxError
    from ara.docx_package.checkpoint import CheckpointError, decode_metadata, encode_metadata
    from ara.docx_package.editor import EditorError
    from ara.docx_package.projection import ProjectionError
    from ara.docx_package.session import SessionError
    from ara.models import DocxEditReceipt

    _validate(
        type(document_id) is UUID
        and type(request_id) is UUID
        and type(operation_id) is UUID
        and valid_integer(expected_checkpoint_revision, 1, MAX_REVISION)
        and valid_integer(base_storage_revision, 1, MAX_REVISION)
        and _hash(base_sha256)
    )
    try:
        wire = encode_metadata(metadata, data=data, saved_sha256=base_sha256, phase="working")
        wire["pending"] = {"operation_id": str(operation_id), "request_sha256": "0" * 64}
        wire["pending"]["request_sha256"] = pending_fingerprint(
            document_id,
            expected_checkpoint_revision + 1,
            base_storage_revision,
            base_sha256,
            data,
            wire,
        )
        decode_metadata(wire, data=data, saved_sha256=base_sha256, phase="pending")
    except (DocxError, CheckpointError, EditorError, ProjectionError, SessionError) as exc:
        status = 413 if exc.code.endswith("_limit_exceeded") else 422
        raise DocumentError(status, exc.code, exc.message) from None
    fingerprint = checkpoint_fingerprint(
        "prepare",
        document_id,
        expected_checkpoint_revision,
        request_id,
        base_revision=base_storage_revision,
        base_sha256=base_sha256,
        data=data,
        metadata=wire,
        operation_id=operation_id,
    )
    with _session(runtime) as session:
        document, row = _scope(session, runtime, document_id)
        if not _identity(row, expected_checkpoint_revision, request_id, fingerprint):
            if session.get(DocxEditReceipt, (document_id, operation_id)) is not None:
                _conflict("idempotency_conflict")
            if (document.storage_revision, document.current_sha256) != (
                base_storage_revision,
                base_sha256,
            ):
                _conflict("docx_conflict")
            if (
                base_storage_revision == MAX_REVISION
                or expected_checkpoint_revision >= MAX_REVISION - 1
            ):
                _conflict("revision_exhausted")
            row.phase, row.base_storage_revision, row.base_sha256 = (
                "pending",
                base_storage_revision,
                base_sha256,
            )
            row.working_data, row.working_sha256 = data, sha256(data).hexdigest()
            row.checkpoint_metadata = wire
            _transition(row, request_id, fingerprint)
            session.flush()
        result = _prepared(_reply(document, row))
    return result
