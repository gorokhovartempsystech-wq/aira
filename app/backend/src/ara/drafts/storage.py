"""Transactional storage of one current draft per existing document."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ara.documents.runtime import DocumentRuntime
from ara.drafts.schemas import MAX_REVISION, DraftSnapshot, _valid_text
from ara.models import Document, DocumentDraft, DocumentVersion

if TYPE_CHECKING:
    from ara.documents.storage import DocumentError


def _invalid_request() -> DocumentError:
    from ara.documents.storage import DocumentError

    return DocumentError(422, "validation_error", "Invalid request")


def _lock_document(
    session: Session, runtime: DocumentRuntime, document_id: UUID, *, read: bool
) -> None:
    # _session already holds Project FOR SHARE. Match append_version's lock
    # order and recheck project membership on the row returned after any wait.
    document = session.scalar(
        select(Document.id)
        .where(Document.id == document_id, Document.project_id == runtime.project_id)
        .with_for_update(read=read)
    )
    if document is None:
        from ara.documents.storage import _not_found

        raise _not_found()


def _has_base(session: Session, document_id: UUID, base_version_id: UUID) -> bool:
    return (
        session.scalar(
            select(DocumentVersion.id).where(
                DocumentVersion.id == base_version_id,
                DocumentVersion.document_id == document_id,
            )
        )
        is not None
    )


def _snapshot(session: Session, draft: DocumentDraft, document_id: UUID) -> DraftSnapshot:
    snapshot = DraftSnapshot.model_validate(draft)
    if snapshot.document_id != document_id or not _has_base(
        session, document_id, snapshot.base_version_id
    ):
        raise ValueError("Invalid stored draft identity")
    return snapshot


def read_draft(runtime: DocumentRuntime, *, document_id: UUID) -> DraftSnapshot | None:
    """Read without creating a draft, holding current access through commit."""
    # The legacy storage module builds Pydantic schemas when imported. Load it
    # only on an explicit operation, keeping every drafts module import inert.
    from ara.documents.storage import _session

    if not isinstance(document_id, UUID):
        raise _invalid_request()

    with _session(runtime) as session:
        _lock_document(session, runtime, document_id, read=True)
        draft = session.get(DocumentDraft, document_id)
        result = None if draft is None else _snapshot(session, draft, document_id)
    return result


def save_draft(
    runtime: DocumentRuntime,
    *,
    document_id: UUID,
    expected_revision: int,
    base_version_id: UUID,
    content_markdown: str,
) -> DraftSnapshot:
    """Replace the full draft only if its revision still matches the caller's."""
    from ara.documents.storage import DocumentError, _not_found, _session

    if (
        not isinstance(document_id, UUID)
        or not isinstance(base_version_id, UUID)
        or type(expected_revision) is not int
        or not 0 <= expected_revision < MAX_REVISION
    ):
        raise _invalid_request()
    try:
        _valid_text(content_markdown)
    except ValueError:
        raise _invalid_request() from None

    with _session(runtime) as session:
        # Lock the existing document even when there is no draft to lock yet.
        # This serializes first INSERTs as well as later UPDATEs.
        _lock_document(session, runtime, document_id, read=False)
        if not _has_base(session, document_id, base_version_id):
            raise _not_found()

        draft = session.get(DocumentDraft, document_id)
        revision = 0 if draft is None else _snapshot(session, draft, document_id).revision
        if revision != expected_revision:
            raise DocumentError(409, "draft_conflict", "Document draft has changed")

        if draft is None:
            draft = DocumentDraft(document_id=document_id)
            session.add(draft)
        draft.base_version_id = base_version_id
        draft.revision = expected_revision + 1
        draft.content_markdown = content_markdown
        # Evaluate the database clock after obtaining the locks, on every save,
        # including when the caller submits the very same text again.
        draft.updated_at = func.clock_timestamp()
        session.flush()
        session.refresh(draft)
        result = _snapshot(session, draft, document_id)
    # _session commits before returning and rolls back write/commit failures.
    return result
