"""Metadata-only scope observations, held until a prepared reply is validated."""

from contextlib import contextmanager
from dataclasses import dataclass, field

from ara.docx_documents._dto import MAX_REVISION, DocxSummary, valid_integer


@dataclass(frozen=True, slots=True)
class Observation:
    document: DocxSummary = field(repr=False)
    revision: int
    phase: str


def summary(document):
    return DocxSummary(
        document.document_id,
        document.title,
        document.storage_revision,
        document.current_sha256,
        len(document.current_data),
        document.created_at,
        document.updated_at,
    )


@contextmanager
def scoped_document(runtime, document_id):
    """Authorize RAM rescue without depending on current/receipt/checkpoint validity."""
    from sqlalchemy import select

    from ara.documents.storage import _not_found, _session
    from ara.models import DocxDocument

    with _session(runtime) as session:
        found = session.scalar(
            select(DocxDocument.id)
            .where(DocxDocument.id == document_id, DocxDocument.project_id == runtime.project_id)
            .with_for_update(read=True)
        )
        if found is None:
            raise _not_found()
        yield session


@contextmanager
def observe(runtime, document_id):
    from sqlalchemy import func, select

    from ara.documents.storage import _not_found, _session
    from ara.models import DocxDocument, DocxEditorCheckpoint

    with _session(runtime) as session:
        row = (
            session.execute(
                select(
                    DocxDocument.id.label("document_id"),
                    DocxDocument.title,
                    DocxDocument.storage_revision,
                    DocxDocument.current_sha256,
                    func.octet_length(DocxDocument.current_data).label("current_size_bytes"),
                    DocxDocument.created_at,
                    DocxDocument.updated_at,
                )
                .where(
                    DocxDocument.id == document_id, DocxDocument.project_id == runtime.project_id
                )
                .with_for_update(read=True)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise _not_found()
        doc = DocxSummary(**row)
        cp = session.execute(
            select(
                DocxEditorCheckpoint.checkpoint_revision,
                DocxEditorCheckpoint.phase,
                DocxEditorCheckpoint.format_version,
            ).where(DocxEditorCheckpoint.document_id == document_id)
        ).one_or_none()
        if cp is not None and (
            not valid_integer(cp.checkpoint_revision, 1, MAX_REVISION)
            or type(cp.phase) is not str
            or cp.phase not in ("empty", "working", "pending")
            or type(cp.format_version) is not int
            or cp.format_version != 1
        ):
            raise ValueError("Invalid stored editor fence")
        yield Observation(doc, cp.checkpoint_revision if cp else 0, cp.phase if cp else "absent")
