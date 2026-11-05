"""One transaction for a manual span edit and its durable retry receipt."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from ara.documents.runtime import DocumentRuntime
    from ara.docx_documents._dto import DocxSummary
    from ara.docx_documents.text_edit_schemas import TextEditRequest


def save_edit(
    runtime: "DocumentRuntime",
    *,
    document_id: "UUID",
    operation_id: "UUID",
    body: "TextEditRequest",
) -> "DocxSummary":
    import json
    import re
    from hashlib import sha256

    from sqlalchemy import func

    from ara.documents.storage import DocumentError, _session
    from ara.docx_documents._dto import DocxSummary
    from ara.docx_documents.storage import _document, _snapshot, _validate_package
    from ara.docx_package import DocxError
    from ara.docx_package.editing import EditError, TextEdit, export_docx
    from ara.docx_package.projection import ProjectionError, SourceAnchor
    from ara.models import DocxEditReceipt

    fingerprint = sha256(
        json.dumps(
            body.model_dump(), sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    expected = int(body.expected_storage_revision)

    def summary(value):
        return DocxSummary(
            document_id=value.document_id,
            title=value.title,
            storage_revision=value.storage_revision,
            current_sha256=value.current_sha256,
            current_size_bytes=value.current_size_bytes,
            created_at=value.document_created_at,
            updated_at=value.document_updated_at,
        )

    with _session(runtime) as session:
        # Every writer, including old CAS-only writers, locks this same row.
        # Acquire it before looking for a receipt so simultaneous first attempts
        # see the winner's committed receipt rather than both applying the edit.
        document = _document(session, runtime, document_id, writing=True)
        previous = _snapshot(document)
        receipt = session.get(DocxEditReceipt, (document_id, operation_id))
        if receipt is not None:
            result = summary(receipt)
            if (
                re.fullmatch("[0-9a-f]{64}", receipt.request_sha256) is None
                or not 2 <= result.storage_revision <= previous.storage_revision
                or result.created_at != previous.created_at
                or (
                    result.storage_revision == previous.storage_revision
                    and (
                        result.title != previous.title
                        or result.current_sha256 != previous.current_sha256
                        or result.current_size_bytes != len(previous.current_data)
                        or result.updated_at != previous.updated_at
                    )
                )
            ):
                raise ValueError("Invalid stored edit receipt")
            if receipt.request_sha256 != fingerprint:
                raise DocumentError(409, "idempotency_conflict", "Edit attempt does not match")
        else:
            if previous.storage_revision != expected:
                raise DocumentError(409, "docx_conflict", "Document storage revision has changed")
            anchor = SourceAnchor(
                body.anchor.source_sha256, body.anchor.part_name, tuple(body.anchor.path)
            )
            try:
                data = export_docx(
                    previous.current_data,
                    (TextEdit(anchor, body.expected_text, body.replacement_text),),
                )
                _validate_package(data)
            except EditError as exc:
                status = 409 if exc.code in ("stale_source", "text_mismatch") else 422
                if exc.code == "edit_limit_exceeded":
                    status = 413
                raise DocumentError(status, exc.code, exc.message) from None
            except (DocxError, ProjectionError) as exc:
                status = (
                    413
                    if exc.code in ("package_limit_exceeded", "projection_limit_exceeded")
                    else 422
                )
                raise DocumentError(status, exc.code, exc.message) from None
            document.current_data = data
            document.current_sha256 = sha256(data).hexdigest()
            document.storage_revision = previous.storage_revision + 1
            document.updated_at = func.clock_timestamp()
            session.flush()
            saved = _snapshot(document)
            receipt = DocxEditReceipt(
                document_id=document_id,
                operation_id=operation_id,
                request_sha256=fingerprint,
                title=saved.title,
                storage_revision=saved.storage_revision,
                current_sha256=saved.current_sha256,
                current_size_bytes=len(saved.current_data),
                document_created_at=saved.created_at,
                document_updated_at=saved.updated_at,
            )
            session.add(receipt)
            session.flush()
            result = summary(receipt)
    # Both the package and receipt have committed before exposing success.
    return result
