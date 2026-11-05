"""Explicitly scoped working copy transactions; imports perform no setup."""


def recover(runtime, document_id, body=None, *, deleting=False):
    from uuid import UUID

    from sqlalchemy import func, select

    from ara.documents.storage import DocumentError, _not_found, _session
    from ara.docx_documents.recovery_schemas import RecoveryEnvelope, RecoveryRecord
    from ara.models import DocxDocument, DocxEditDraft

    from .checkpoints import _legacy_fence, _legacy_guard

    def conflict():
        raise DocumentError(409, "draft_conflict", "Document draft has changed")

    def record(row):
        return RecoveryRecord.model_validate(
            {
                **row.payload,
                "token": str(row.token),
                "updated_at": row.updated_at,
            }
        )

    with _session(runtime) as session:
        # Lock only the ID; checkpointing never loads or parses Word bytes.
        found = session.scalar(
            select(DocxDocument.id)
            .where(DocxDocument.id == document_id, DocxDocument.project_id == runtime.project_id)
            .with_for_update(read=body is None)
        )
        if found is None:
            raise _not_found()
        row = session.get(DocxEditDraft, document_id)
        checkpoint_revision = _legacy_guard(session, document_id, row is not None)
        existing = record(row) if row is not None else None
        if body is not None:
            expected = UUID(body.expected_token) if body.expected_token is not None else None
            if deleting:
                if row is not None:
                    if row.token != expected:
                        conflict()
                    session.delete(row)
                    session.flush()
                existing = None
            else:
                token = UUID(body.token)
                payload = body.model_dump(include={"edit", "operation_id"})
                if row is not None and row.token == token:
                    if row.payload != payload:
                        conflict()
                else:
                    if (row is None and expected is not None) or (
                        row is not None and row.token != expected
                    ):
                        conflict()
                    if row is None:
                        row = DocxEditDraft(document_id=document_id, token=token, payload=payload)
                        session.add(row)
                    else:
                        row.token, row.payload = token, payload
                        row.updated_at = func.clock_timestamp()
                    session.flush()
                    existing = record(row)
                    _legacy_fence(session, document_id, checkpoint_revision)
        result = RecoveryEnvelope(document_id=document_id, draft=existing)
    return result
