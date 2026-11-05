"""Explicit scoped transactions for exact working copies, separate from current."""

from hashlib import sha256
from uuid import UUID

from ._dto import MAX_REVISION, _hash, valid_integer
from .checkpoint_fingerprints import checkpoint_fingerprint, pending_fingerprint


def _conflict(code):
    from ara.documents.storage import DocumentError

    messages = {
        "checkpoint_conflict": "Document checkpoint has changed",
        "idempotency_conflict": "Checkpoint attempt does not match",
        "legacy_draft_present": "Resolve the existing text draft first",
        "draft_mode_conflict": "A full document checkpoint is active",
        "docx_conflict": "Document storage revision has changed",
        "pending_save_required": "Resolve the pending save first",
        "revision_exhausted": "Document checkpoint revision is exhausted",
    }
    raise DocumentError(409, code, messages[code])


def _validate(condition):
    if not condition:
        from ara.documents.storage import DocumentError

        raise DocumentError(422, "validation_error", "Invalid request")


def _record(row):
    from ara.docx_package.checkpoint import decode_metadata

    from .checkpoint_models import CheckpointRecord

    metadata = None
    if row.phase != "empty":
        if (
            type(row.working_data) is not bytes
            or sha256(row.working_data).hexdigest() != row.working_sha256
        ):
            raise ValueError("Invalid stored DOCX checkpoint hash")
        metadata = decode_metadata(
            row.checkpoint_metadata,
            data=row.working_data,
            saved_sha256=row.base_sha256,
            phase=row.phase,
        )
        if (
            row.phase == "pending"
            and pending_fingerprint(
                row.document_id,
                row.checkpoint_revision,
                row.base_storage_revision,
                row.base_sha256,
                row.working_data,
                row.checkpoint_metadata,
            )
            != metadata.pending.request_sha256
        ):
            raise ValueError("Invalid stored DOCX pending identity")
    elif row.checkpoint_metadata is not None:
        raise ValueError("Invalid stored DOCX empty checkpoint")
    return CheckpointRecord(
        row.document_id,
        row.checkpoint_revision,
        row.format_version,
        row.phase,
        row.base_storage_revision,
        row.base_sha256,
        row.working_data,
        row.working_sha256,
        metadata,
        row.last_request_id,
        row.last_request_sha256,
        row.updated_at,
    )


def _legacy(session, document_id, row):
    from ara.models import DocxEditDraft

    if session.get(DocxEditDraft, document_id) is not None:
        if row is not None and row.phase != "empty":
            raise ValueError("Conflicting stored DOCX draft modes")
        _conflict("legacy_draft_present")


def _scope(session, runtime, document_id):
    from ara.models import DocxEditorCheckpoint

    from .storage import _document, _snapshot

    document = _snapshot(_document(session, runtime, document_id, writing=True))
    row = session.get(DocxEditorCheckpoint, document_id)
    _legacy(session, document_id, row)
    if row is not None:
        _record(row)
    return document, row


def _reply(document, row):
    from .checkpoint_models import CheckpointSnapshot

    return CheckpointSnapshot(document, _record(row))


def get_checkpoint(runtime, *, document_id):
    from ara.documents.storage import _session
    from ara.models import DocxEditorCheckpoint

    _validate(type(document_id) is UUID)
    with _session(runtime) as session:
        document, row = _scope(session, runtime, document_id)
        if row is None:
            row = DocxEditorCheckpoint(
                document_id=document_id, checkpoint_revision=1, format_version=1, phase="empty"
            )
            session.add(row)
            session.flush()
        result = _reply(document, row)
    return result


def _identity(row, expected, request_id, fingerprint):
    if row is None:
        _conflict("checkpoint_conflict")
    if row.checkpoint_revision == expected + 1 and row.last_request_id == request_id:
        if row.last_request_sha256 != fingerprint:
            _conflict("idempotency_conflict")
        return True
    if row.checkpoint_revision != expected:
        _conflict("checkpoint_conflict")
    if row.phase == "pending":
        _conflict("pending_save_required")
    if expected == MAX_REVISION:
        _conflict("revision_exhausted")
    return False


def _transition(row, request_id, fingerprint):
    from sqlalchemy import func

    row.checkpoint_revision += 1
    row.last_request_id, row.last_request_sha256 = request_id, fingerprint
    row.updated_at = func.clock_timestamp()


def put_checkpoint(
    runtime,
    *,
    document_id,
    expected_checkpoint_revision,
    request_id,
    base_storage_revision,
    base_sha256,
    data,
    metadata,
):
    from ara.documents.storage import DocumentError, _session
    from ara.docx_package import DocxError
    from ara.docx_package.checkpoint import CheckpointError, encode_metadata
    from ara.docx_package.editor import EditorError
    from ara.docx_package.projection import ProjectionError
    from ara.docx_package.session import SessionError

    _validate(
        type(document_id) is UUID
        and type(request_id) is UUID
        and valid_integer(expected_checkpoint_revision, 1, MAX_REVISION)
        and valid_integer(base_storage_revision, 1, MAX_REVISION)
        and _hash(base_sha256)
    )
    try:
        wire = encode_metadata(metadata, data=data, saved_sha256=base_sha256, phase="working")
    except (DocxError, CheckpointError, EditorError, ProjectionError, SessionError) as exc:
        status = 413 if exc.code.endswith("_limit_exceeded") else 422
        raise DocumentError(status, exc.code, exc.message) from None
    fingerprint = checkpoint_fingerprint(
        "put",
        document_id,
        expected_checkpoint_revision,
        request_id,
        base_revision=base_storage_revision,
        base_sha256=base_sha256,
        data=data,
        metadata=wire,
    )
    with _session(runtime) as session:
        document, row = _scope(session, runtime, document_id)
        if not _identity(row, expected_checkpoint_revision, request_id, fingerprint):
            if (document.storage_revision, document.current_sha256) != (
                base_storage_revision,
                base_sha256,
            ):
                _conflict("docx_conflict")
            row.phase, row.base_storage_revision, row.base_sha256 = (
                "working",
                base_storage_revision,
                base_sha256,
            )
            row.working_data, row.working_sha256 = data, sha256(data).hexdigest()
            row.checkpoint_metadata = wire
            _transition(row, request_id, fingerprint)
            session.flush()
        result = _reply(document, row)
    return result


def discard_checkpoint(runtime, *, document_id, expected_checkpoint_revision, request_id):
    from sqlalchemy import null

    from ara.documents.storage import _session

    _validate(
        type(document_id) is UUID
        and type(request_id) is UUID
        and valid_integer(expected_checkpoint_revision, 1, MAX_REVISION)
    )
    fingerprint = checkpoint_fingerprint(
        "discard", document_id, expected_checkpoint_revision, request_id
    )
    with _session(runtime) as session:
        document, row = _scope(session, runtime, document_id)
        if not _identity(row, expected_checkpoint_revision, request_id, fingerprint):
            row.phase = "empty"
            row.base_storage_revision = row.base_sha256 = row.working_data = None
            row.working_sha256 = None
            # JSONB's None binder emits JSON null; an empty slot requires SQL NULL.
            row.checkpoint_metadata = null()
            _transition(row, request_id, fingerprint)
            session.flush()
        result = _reply(document, row)
    return result


def _legacy_guard(session, document_id, legacy_exists):
    from sqlalchemy import select

    from ara.models import DocxEditorCheckpoint

    row = session.execute(
        select(
            DocxEditorCheckpoint.phase,
            DocxEditorCheckpoint.format_version,
            DocxEditorCheckpoint.checkpoint_revision,
        ).where(DocxEditorCheckpoint.document_id == document_id)
    ).one_or_none()
    if row is None:
        return None
    if (
        type(row.phase) is not str
        or row.phase not in ("empty", "working", "pending")
        or type(row.format_version) is not int
        or row.format_version != 1
        or not valid_integer(row.checkpoint_revision, 1, MAX_REVISION)
    ):
        raise ValueError("Invalid stored DOCX checkpoint fence")
    if row.phase != "empty":
        if legacy_exists:
            raise ValueError("Conflicting stored DOCX draft modes")
        _conflict("draft_mode_conflict")
    return row.checkpoint_revision


def _legacy_fence(session, document_id, revision):
    from sqlalchemy import func, update

    from ara.models import DocxEditorCheckpoint

    if revision is None:
        return
    if revision == MAX_REVISION:
        _conflict("revision_exhausted")
    result = session.execute(
        update(DocxEditorCheckpoint)
        .where(
            DocxEditorCheckpoint.document_id == document_id,
            DocxEditorCheckpoint.checkpoint_revision == revision,
        )
        .values(
            checkpoint_revision=revision + 1,
            last_request_id=None,
            last_request_sha256=None,
            updated_at=func.clock_timestamp(),
        )
    )
    if result.rowcount != 1:
        raise ValueError("Invalid stored DOCX checkpoint fence")
