"""One scoped transaction for a paragraph batch and its namespaced retry receipt."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from ara.documents.runtime import DocumentRuntime

    from ._dto import DocxSummary
    from .paragraph_schemas import ParagraphCommandsRequest


def save_commands(
    runtime: "DocumentRuntime",
    *,
    document_id: "UUID",
    operation_id: "UUID",
    body: "ParagraphCommandsRequest",
) -> "DocxSummary":
    import json
    import re
    from hashlib import sha256
    from uuid import UUID

    from sqlalchemy import func

    from ara.documents.storage import DocumentError, _session
    from ara.docx_package import DocxError
    from ara.docx_package.formatting import FormattingError, export_formats
    from ara.docx_package.projection import ProjectionError
    from ara.docx_package.structure import StructureError, export_structure
    from ara.models import DocxEditReceipt

    from ._dto import DocxSummary
    from .paragraph_schemas import ParagraphCommandsRequest
    from .storage import _document, _snapshot, _validate_package

    if (
        not isinstance(document_id, UUID)
        or not isinstance(operation_id, UUID)
        or type(body) is not ParagraphCommandsRequest
    ):
        raise DocumentError(422, "validation_error", "Invalid request")
    try:
        body = ParagraphCommandsRequest.model_validate(body.model_dump(warnings=False))
    except (ValueError, TypeError, RecursionError):
        raise DocumentError(422, "validation_error", "Invalid request") from None
    fingerprint = sha256(
        b"ara.docx.paragraph-commands.v1\0"
        + json.dumps(
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
        # Shared project/document lock order is also used by old CAS writers.
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
            commands = tuple(command.native() for command in body.commands)
            try:
                export = export_structure if body.kind == "structure" else export_formats
                data = export(previous.current_data, commands)
                _validate_package(data)
            except (StructureError, FormattingError, DocxError, ProjectionError) as exc:
                status = 409 if exc.code in ("stale_source", "text_mismatch") else 422
                if exc.code.endswith("_limit_exceeded"):
                    status = 413
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
    return result
