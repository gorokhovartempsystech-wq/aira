"""Confirm pending cleanup only with a receipt bound to the complete save proof."""

from uuid import UUID

from ._dto import MAX_REVISION
from .checkpoint_fingerprints import _fingerprint
from .checkpoints import _conflict, _validate
from .save_commit import _committed, _handle, _matches


def _save_conflict(code):
    if code == "save_unconfirmed":
        from ara.documents.storage import DocumentError

        raise DocumentError(409, code, "Save has not been confirmed")
    _conflict(code)


def _control_fingerprint(action, handle, request_id):
    return _fingerprint(
        b"ara.docx.editor-checkpoint.v1\0",
        {
            "version": 1,
            "action": action,
            "document_id": str(handle.document_id),
            "expected_checkpoint_revision": str(handle.prepared_checkpoint_revision),
            "request_id": str(request_id),
            "operation_id": str(handle.operation_id),
            "save_request_sha256": handle.request_sha256,
        },
    )


def _control_state(record, handle, request_id, fingerprint, action):
    if record is None:
        _conflict("checkpoint_conflict")
    if record.checkpoint_revision == handle.prepared_checkpoint_revision + 1:
        if record.last_request_id == request_id:
            if record.last_request_sha256 != fingerprint:
                _conflict("idempotency_conflict")
            return True
        if (
            record.last_request_id is not None
            and record.last_request_sha256
            == _control_fingerprint(action, handle, record.last_request_id)
        ):
            return True
        _conflict("checkpoint_conflict")
    if not _matches(record, handle):
        _conflict("checkpoint_conflict")
    if record.checkpoint_revision == MAX_REVISION:
        _conflict("revision_exhausted")
    return False


def get_save_status(runtime, *, handle):
    from ara.documents.storage import _session
    from ara.models import DocxEditorCheckpoint, DocxEditReceipt

    from .checkpoints import _legacy, _record
    from .save_models import SaveStatus
    from .storage import _document, _snapshot

    handle = _handle(handle)
    with _session(runtime) as session:
        document = _snapshot(_document(session, runtime, handle.document_id))
        receipt = session.get(DocxEditReceipt, (handle.document_id, handle.operation_id))
        if receipt is not None:
            committed = _committed(document, receipt, handle)
            state = "committed" if committed.current_matches_receipt else "committed_outdated"
            result = SaveStatus(state, document, handle, committed.receipt, None)
        else:
            row = session.get(DocxEditorCheckpoint, handle.document_id)
            _legacy(session, handle.document_id, row)
            record = _record(row) if row is not None else None
            state = "superseded"
            if record is not None and _matches(record, handle):
                if (document.storage_revision, document.current_sha256) != (
                    handle.base_storage_revision,
                    handle.base_sha256,
                ):
                    state = "conflict"
                elif (
                    record.checkpoint_revision == MAX_REVISION
                    or handle.base_storage_revision == MAX_REVISION
                ):
                    state = "exhausted"
                else:
                    state = "ready"
            result = SaveStatus(
                state,
                document,
                handle,
                None,
                record.checkpoint_revision if record is not None else None,
            )
    return result


def finalize_save(runtime, *, handle, request_id):
    from ara.documents.storage import _session
    from ara.docx_package.checkpoint import CheckpointMetadata, encode_metadata
    from ara.models import DocxEditorCheckpoint, DocxEditReceipt

    from .checkpoints import _legacy, _record, _reply, _transition
    from .save_models import FinalizedSave
    from .storage import _document, _snapshot

    handle = _handle(handle)
    _validate(type(request_id) is UUID)
    fingerprint = _control_fingerprint("finalize", handle, request_id)
    with _session(runtime) as session:
        document = _snapshot(_document(session, runtime, handle.document_id, writing=True))
        receipt = session.get(DocxEditReceipt, (handle.document_id, handle.operation_id))
        if receipt is None:
            _save_conflict("save_unconfirmed")
        committed = _committed(document, receipt, handle)
        row = session.get(DocxEditorCheckpoint, handle.document_id)
        record = _record(row) if row is not None else None
        complete = _control_state(record, handle, request_id, fingerprint, "finalize")
        if not complete:
            _legacy(session, handle.document_id, row)
            if not committed.current_matches_receipt:
                _conflict("docx_conflict")
            metadata = CheckpointMetadata(handle.metadata.selection, handle.metadata.origin)
            wire = encode_metadata(
                metadata, data=row.working_data, saved_sha256=handle.working_sha256, phase="working"
            )
            row.phase = "working"
            row.base_storage_revision, row.base_sha256 = (
                committed.receipt.storage_revision,
                handle.working_sha256,
            )
            row.checkpoint_metadata = wire
            _transition(row, request_id, fingerprint)
            session.flush()
        result = FinalizedSave(_reply(document, row), committed.receipt, handle)
    return result
