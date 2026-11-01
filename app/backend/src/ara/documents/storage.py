"""Owner-scoped transactions and immutable application-level version appends."""

from contextlib import contextmanager
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ara.documents.markdown import split_markdown
from ara.documents.runtime import DocumentRuntime
from ara.documents.schemas import AppendVersion, VersionResponse
from ara.models import Document, DocumentVersion, Project


class DocumentError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


def _not_found() -> DocumentError:
    return DocumentError(404, "not_found", "Document or version not found")


@contextmanager
def _session(runtime: DocumentRuntime):
    """Hold project ownership stable until this operation commits or rolls back."""
    try:
        with Session(runtime.engine) as session, session.begin():
            project = session.scalar(
                select(Project.id)
                .where(Project.id == runtime.project_id, Project.owner_id == runtime.user_id)
                .with_for_update(read=True)
            )
            if project is None:
                raise _not_found()
            yield session
    except DocumentError:
        raise
    except OperationalError:
        raise DocumentError(
            503, "storage_unavailable", "Document storage is unavailable", True
        ) from None
    except Exception:
        # Roll back before emitting a safe error, including failures during commit.
        raise DocumentError(500, "storage_error", "Document storage operation failed") from None


def _manual_version(
    document_id: UUID, parent_version_id: UUID | None, content_markdown: str
) -> DocumentVersion:
    blocks = split_markdown(content_markdown)
    return DocumentVersion(
        document_id=document_id,
        parent_version_id=parent_version_id,
        content_markdown=content_markdown,
        blocks=blocks,
        provenance={"source": "manual"},
        import_omissions=[
            {"block_id": block["id"], "reason": "Unclosed fenced code block"}
            for block in blocks
            if block["kind"] == "unsupported"
        ],
    )


def append_version(
    runtime: DocumentRuntime,
    *,
    document_id: UUID,
    expected_version_id: UUID,
    content_markdown: str,
) -> VersionResponse:
    """Append against the current version atomically, without modifying old snapshots.

    The caller owns the engine; each call owns its session and transaction.
    Access is checked before comparing versions so conflicts cannot expose history.
    """
    try:
        body = AppendVersion(
            document_id=document_id,
            expected_version_id=expected_version_id,
            content_markdown=content_markdown,
        )
    except ValidationError:
        raise DocumentError(422, "validation_error", "Invalid request") from None

    with _session(runtime) as session:
        document = session.scalar(
            select(Document)
            .where(Document.id == body.document_id, Document.project_id == runtime.project_id)
            .with_for_update()
        )
        if document is None:
            raise _not_found()
        if document.current_version_id != body.expected_version_id:
            raise DocumentError(409, "version_conflict", "Document version has changed")
        version = _manual_version(document.id, body.expected_version_id, body.content_markdown)
        session.add(version)
        session.flush()
        document.current_version_id = version.id
        session.flush()
        result = VersionResponse.model_validate(version).model_copy(deep=True)
    # Leaving _session commits successfully before a detached snapshot is returned.
    return result
