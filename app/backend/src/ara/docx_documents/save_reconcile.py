"""Explicit pending discard and restartable composition of durable save steps."""

from uuid import UUID

from .checkpoints import _validate
from .save_commit import _committed, _handle, commit_save
from .save_finalize import _control_fingerprint, _control_state, finalize_save


def discard_pending(runtime, *, handle, request_id):
    from sqlalchemy import null

    from ara.documents.storage import _session
    from ara.models import DocxEditorCheckpoint, DocxEditReceipt

    from .checkpoints import _legacy, _record, _reply, _transition
    from .save_models import DiscardedSave
    from .storage import _document, _snapshot

    handle = _handle(handle)
    _validate(type(request_id) is UUID)
    fingerprint = _control_fingerprint("discard-pending", handle, request_id)
    with _session(runtime) as session:
        document = _snapshot(_document(session, runtime, handle.document_id, writing=True))
        receipt = session.get(DocxEditReceipt, (handle.document_id, handle.operation_id))
        summary = _committed(document, receipt, handle).receipt if receipt is not None else None
        row = session.get(DocxEditorCheckpoint, handle.document_id)
        record = _record(row) if row is not None else None
        complete = _control_state(record, handle, request_id, fingerprint, "discard-pending")
        if not complete:
            _legacy(session, handle.document_id, row)
            row.phase = "empty"
            row.base_storage_revision = row.base_sha256 = row.working_data = None
            row.working_sha256 = None
            row.checkpoint_metadata = null()
            _transition(row, request_id, fingerprint)
            session.flush()
        result = DiscardedSave(_reply(document, row), handle, summary)
    return result


def reconcile_save(runtime, *, handle, request_id):
    # Validate the full control input before commit_save can change current.
    handle = _handle(handle)
    _validate(type(request_id) is UUID)
    committed = commit_save(runtime, handle=handle)
    return finalize_save(runtime, handle=committed.handle, request_id=request_id)
