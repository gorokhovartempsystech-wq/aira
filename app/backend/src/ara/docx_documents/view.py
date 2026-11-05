"""Bounded read-only projection of a single validated storage snapshot."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ara.documents.runtime import DocumentRuntime


def install_docx_view(app: "FastAPI", runtime: "DocumentRuntime") -> None:
    from dataclasses import fields, is_dataclass

    from fastapi import APIRouter, Request, Response

    from ara.documents.storage import DocumentError
    from ara.docx_documents import get_docx
    from ara.docx_documents.view_schemas import DocxView
    from ara.docx_package.projection import project_docx
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID

    errors = {
        code: {"model": DraftErrorResponse, "description": description}
        for code, description in (
            (404, "Document not found"),
            (413, "Document view exceeds a technical limit"),
            (422, "Invalid request"),
            (500, "Document storage operation failed"),
            (503, "Document storage is unavailable"),
        )
    }

    def too_large():
        raise DocumentError(413, "view_limit_exceeded", "DOCX view exceeds a technical limit")

    def prepare(snapshot):
        projection = project_docx(snapshot.current_data)
        records, characters = 0, 0

        def wire(value):
            nonlocal records, characters
            if is_dataclass(value):
                records += 1
                if records > 5000:
                    too_large()
                return {field.name: wire(getattr(value, field.name)) for field in fields(value)}
            if isinstance(value, tuple):
                return [wire(item) for item in value]
            if isinstance(value, str):
                characters += len(value)
                if characters > 1000000:
                    too_large()
            return value

        result = DocxView(
            document_id=snapshot.document_id,
            title=snapshot.title,
            storage_revision=str(snapshot.storage_revision),
            current_sha256=snapshot.current_sha256,
            current_size_bytes=len(snapshot.current_data),
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            body_anchor=wire(projection.body_anchor),
            coverage_scope=projection.coverage_scope,
            has_unprojected_content=projection.has_unprojected_content,
            blocks=wire(projection.blocks),
            notices=wire(projection.notices),
        )
        encoded = result.model_dump_json().encode("utf-8")
        if len(encoded) > 8 * 1024 * 1024:
            too_large()
        return Response(
            encoded, media_type="application/json", headers={"Cache-Control": "no-store"}
        )

    router = APIRouter()

    @router.get("/docx-documents/{document_id}/view", response_model=DocxView, responses=errors)
    def read_view(document_id: HttpUUID, request: Request):
        if request.query_params:
            raise DocumentError(422, "validation_error", "Invalid request")
        try:
            return prepare(get_docx(runtime, document_id=document_id))
        except DocumentError:
            raise
        except Exception:
            raise DocumentError(500, "storage_error", "Document storage operation failed") from None

    app.include_router(router)
