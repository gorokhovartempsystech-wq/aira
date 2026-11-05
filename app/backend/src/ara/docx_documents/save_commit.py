"""Commit a durable pending candidate and its receipt in one scoped transaction."""

from copy import deepcopy

from ._dto import MAX_REVISION, DocxSummary, _hash
from .checkpoints import _conflict
from .save_models import CommittedSave, SaveHandle


def _handle(value):
    from ara.documents.storage import DocumentError

    try:
        if type(value) is not SaveHandle:
            raise ValueError("Invalid save handle")
        value.__post_init__()
        detached = deepcopy(value)
        detached.__post_init__()
        return detached
    except (ValueError, TypeError, AttributeError):
        raise DocumentError(422, "validation_error", "Invalid request") from None


def _committed(document, receipt, handle):
    if not _hash(receipt.request_sha256):
        raise ValueError("Invalid stored DOCX receipt")
    if receipt.request_sha256 != handle.request_sha256:
        _conflict("idempotency_conflict")
    if receipt.document_id != handle.document_id or receipt.operation_id != handle.operation_id:
        raise ValueError("Invalid stored DOCX receipt")
    summary = DocxSummary(
        receipt.document_id,
        receipt.title,
        receipt.storage_revision,
        receipt.current_sha256,
        receipt.current_size_bytes,
        receipt.document_created_at,
        receipt.document_updated_at,
    )
    return CommittedSave(summary, document, handle)


def _matches(record, handle):
    return (
        record.phase == "pending"
        and record.document_id == handle.document_id
        and record.checkpoint_revision == handle.prepared_checkpoint_revision
        and record.base_storage_revision == handle.base_storage_revision
        and record.base_sha256 == handle.base_sha256
        and record.working_sha256 == handle.working_sha256
        and len(record.working_data) == handle.working_size_bytes
        and record.metadata == handle.metadata
    )


def commit_save(runtime, *, handle):
    from sqlalchemy import func

    from ara.documents.storage import _session
    from ara.models import DocxEditorCheckpoint, DocxEditReceipt

    from .checkpoints import _legacy, _record
    from .storage import _document, _snapshot

    handle = _handle(handle)
    with _session(runtime) as session:
        document = _document(session, runtime, handle.document_id, writing=True)
        previous = _snapshot(document)
        receipt = session.get(DocxEditReceipt, (handle.document_id, handle.operation_id))
        if receipt is None:
            row = session.get(DocxEditorCheckpoint, handle.document_id)
            _legacy(session, handle.document_id, row)
            if row is None or not _matches(_record(row), handle):
                _conflict("checkpoint_conflict")
            if (previous.storage_revision, previous.current_sha256) != (
                handle.base_storage_revision,
                handle.base_sha256,
            ):
                _conflict("docx_conflict")
            if (
                handle.base_storage_revision == MAX_REVISION
                or handle.prepared_checkpoint_revision == MAX_REVISION
            ):
                _conflict("revision_exhausted")
            # The only byte source is the verified durable pending row.
            document.current_data = row.working_data
            document.current_sha256 = row.working_sha256
            document.storage_revision = previous.storage_revision + 1
            document.updated_at = func.clock_timestamp()
            session.flush()
            previous = _snapshot(document)
            receipt = DocxEditReceipt(
                document_id=handle.document_id,
                operation_id=handle.operation_id,
                request_sha256=handle.request_sha256,
                title=previous.title,
                storage_revision=previous.storage_revision,
                current_sha256=previous.current_sha256,
                current_size_bytes=len(previous.current_data),
                document_created_at=previous.created_at,
                document_updated_at=previous.updated_at,
            )
            session.add(receipt)
            session.flush()
        # Receipt replay deliberately never reads checkpoint/legacy state.
        result = _committed(previous, receipt, handle)
    return result
