"""Scoped PostgreSQL storage with caller-ID replay and strict revision CAS.

Every operation owns one session/transaction, never the supplied engine. The
shared transaction boundary locks Project before this module locks a document,
sanitizes storage failures, and commits before a prepared snapshot is returned.
No document bytes are rewritten, interpreted as Markdown or logged here.
"""

from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ara.documents.runtime import DocumentRuntime
from ara.docx_package import DocxLimits
from ara.docx_package.projection import ProjectionLimits, project_docx
from ara.models import DocxDocument

from ._dto import MAX_REVISION, DocxSummary, StoredDocx, valid_integer, valid_title


def _validate(condition: bool) -> None:
    if not condition:
        from ara.documents.storage import DocumentError

        raise DocumentError(422, "validation_error", "Invalid request") from None


def _validate_package(data: bytes) -> None:
    # Storage always uses the fixed defaults, including for data from sessions
    # whose caller chose to allow larger packages or deeper projections.
    project_docx(data, limits=DocxLimits(), projection_limits=ProjectionLimits())


def _document(
    session: Session, runtime: DocumentRuntime, document_id: UUID, *, writing: bool = False
) -> DocxDocument:
    document = session.scalar(
        select(DocxDocument)
        .where(DocxDocument.id == document_id, DocxDocument.project_id == runtime.project_id)
        .with_for_update(read=not writing)
    )
    if document is None:
        from ara.documents.storage import _not_found

        raise _not_found()
    return document


def _snapshot(document: DocxDocument) -> StoredDocx:
    # Construct/validate within the transaction, so malformed metadata and DTO
    # preparation failures cannot commit a write or escape as a partial result.
    result = StoredDocx(
        document_id=document.id,
        title=document.title,
        original_data=document.original_data,
        original_sha256=document.original_sha256,
        current_data=document.current_data,
        current_sha256=document.current_sha256,
        storage_revision=document.storage_revision,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )
    for data, digest in (
        (result.original_data, result.original_sha256),
        (result.current_data, result.current_sha256),
    ):
        if sha256(data).hexdigest() != digest:
            raise ValueError("Invalid stored DOCX hash")
        # Lower-layer errors here denote stored corruption, so the surrounding
        # storage boundary maps them to storage_error rather than an input error.
        _validate_package(data)
    return result


def import_docx(
    runtime: DocumentRuntime, *, document_id: UUID, title: str, data: bytes
) -> StoredDocx:
    """Import exact bytes once, or recover the latest draft of a matching import."""
    _validate(isinstance(document_id, UUID) and valid_title(title) and type(data) is bytes)
    _validate_package(data)
    digest = sha256(data).hexdigest()
    # The legacy storage module builds Pydantic schemas on import, including
    # plugin discovery. Defer it to explicit operations so this package and all
    # of its submodules can be imported without external I/O.
    from ara.documents.storage import DocumentError, _session

    with _session(runtime) as session:
        # The primary key arbitrates concurrent first imports without aborting
        # the transaction. The subsequent scoped lock reads the winning row.
        session.execute(
            insert(DocxDocument)
            .values(
                id=document_id,
                project_id=runtime.project_id,
                title=title,
                original_data=data,
                original_sha256=digest,
                current_data=data,
                current_sha256=digest,
                storage_revision=1,
            )
            .on_conflict_do_nothing(index_elements=[DocxDocument.id])
        )
        result = _snapshot(_document(session, runtime, document_id))
        if result.title != title or result.original_data != data:
            raise DocumentError(409, "import_conflict", "Document import does not match")
    return result


def get_docx(runtime: DocumentRuntime, *, document_id: UUID) -> StoredDocx:
    """Read both validated packages without changing any persisted field."""
    _validate(isinstance(document_id, UUID))
    from ara.documents.storage import _session

    with _session(runtime) as session:
        result = _snapshot(_document(session, runtime, document_id))
    return result


def list_docx(
    runtime: DocumentRuntime, *, limit: int = 50, offset: int = 0
) -> tuple[DocxSummary, ...]:
    """Return bounded metadata only; package integrity is checked when opened."""
    _validate(valid_integer(limit, 1, 100) and valid_integer(offset, 0, MAX_REVISION))
    from ara.documents.storage import _session

    with _session(runtime) as session:
        rows = session.execute(
            select(
                DocxDocument.id.label("document_id"),
                DocxDocument.title,
                DocxDocument.storage_revision,
                DocxDocument.current_sha256,
                func.octet_length(DocxDocument.current_data).label("current_size_bytes"),
                DocxDocument.created_at,
                DocxDocument.updated_at,
            )
            .where(DocxDocument.project_id == runtime.project_id)
            .order_by(DocxDocument.created_at.desc(), DocxDocument.id.desc())
            .limit(limit)
            .offset(offset)
        ).mappings()
        result = tuple(DocxSummary(**row) for row in rows)
    return result


def save_docx(
    runtime: DocumentRuntime,
    *,
    document_id: UUID,
    expected_storage_revision: int,
    data: bytes,
) -> StoredDocx:
    """Replace the current package only at the exact expected storage revision.

    A lost commit acknowledgement may mean the write succeeded: read back the
    revision and bytes to reconcile it. Repeating an old revision always conflicts,
    even for identical bytes. Session revisions and mark_saved are caller concerns.
    """
    _validate(
        isinstance(document_id, UUID)
        and valid_integer(expected_storage_revision, 1, MAX_REVISION - 1)
        and type(data) is bytes
    )
    _validate_package(data)
    digest = sha256(data).hexdigest()
    from ara.documents.storage import DocumentError, _session

    with _session(runtime) as session:
        document = _document(session, runtime, document_id, writing=True)
        previous = _snapshot(document)
        if previous.storage_revision != expected_storage_revision:
            raise DocumentError(409, "docx_conflict", "Document storage revision has changed")
        document.current_data = data
        document.current_sha256 = digest
        document.storage_revision = previous.storage_revision + 1
        document.updated_at = func.clock_timestamp()
        session.flush()
        result = _snapshot(document)
    return result
