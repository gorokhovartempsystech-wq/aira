"""Bounded binary uploads installed only with an explicit local runtime."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ara.documents.runtime import DocumentRuntime


def install_docx_writes(app: "FastAPI", runtime: "DocumentRuntime") -> None:
    import re

    from fastapi import APIRouter, Depends, Query, Request, Response
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import ClientDisconnect

    from ara.documents.storage import DocumentError
    from ara.docx_documents import import_docx, save_docx
    from ara.docx_documents._dto import MAX_REVISION, valid_title
    from ara.docx_documents.http_schemas import DocxMetadata
    from ara.docx_package import DocxError, DocxLimits
    from ara.docx_package.projection import ProjectionError
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID

    maximum_bytes = DocxLimits().max_archive_bytes
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    media_types = (mime, "application/octet-stream")
    errors = {
        status: {"model": DraftErrorResponse, "description": description}
        for status, description in (
            (404, "Document not found"),
            (409, "Import or storage revision conflict"),
            (413, "Upload exceeds a technical limit"),
            (415, "Unsupported media type"),
            (422, "Invalid request or DOCX package"),
            (500, "Document storage operation failed"),
            (503, "Document storage is unavailable"),
        )
    }

    def invalid():
        raise DocumentError(422, "validation_error", "Invalid request")

    def too_large():
        raise DocumentError(413, "upload_too_large", "DOCX upload exceeds a technical limit")

    def unsupported():
        raise DocumentError(415, "unsupported_media_type", "Unsupported document media type")

    def decimal(value):
        if len(value) > 19 or re.fullmatch(r"[0-9]+", value) is None:
            invalid()
        return int(value)

    def query_value(request, key):
        items = request.query_params.multi_items()
        if len(items) != 1 or items[0][0] != key:
            invalid()
        return items[0][1]

    def import_query(request: Request):
        if not valid_title(query_value(request, "title")):
            invalid()

    def save_query(request: Request):
        revision = decimal(query_value(request, "expected_storage_revision"))
        if not 1 <= revision <= MAX_REVISION - 1:
            invalid()

    async def read_upload(request):
        for name in ("content-type", "content-encoding", "content-length"):
            if len(request.headers.getlist(name)) > 1:
                invalid()
        if request.headers.get("content-type", "").strip().lower() not in media_types:
            unsupported()
        if request.headers.get("content-encoding", "identity").strip().lower() != "identity":
            unsupported()
        length = request.headers.get("content-length")
        if length is not None:
            if "transfer-encoding" in request.headers:
                invalid()
            length = decimal(length)
            if length > maximum_bytes:
                too_large()
        data = bytearray()
        try:
            async for chunk in request.stream():
                if len(data) + len(chunk) > maximum_bytes:
                    too_large()
                data.extend(chunk)
        except ClientDisconnect:
            invalid()
        if length is not None and len(data) != length:
            invalid()
        return bytes(data)

    def perform(operation, **kwargs):
        # ZIP/XML validation, database work and response preparation stay off
        # the event loop. Storage retains transaction and engine ownership.
        try:
            result = operation(runtime, **kwargs)
        except (DocxError, ProjectionError) as exc:
            raise DocumentError(422, exc.code, exc.message) from None
        return DocxMetadata(
            document_id=result.document_id,
            title=result.title,
            storage_revision=result.storage_revision,
            current_sha256=result.current_sha256,
            current_size_bytes=len(result.current_data),
            created_at=result.created_at,
            updated_at=result.updated_at,
        )

    body_schema = {
        "requestBody": {
            "required": True,
            "content": {
                kind: {"schema": {"type": "string", "format": "binary"}} for kind in media_types
            },
        }
    }
    router = APIRouter()

    @router.post(
        "/docx-documents/{document_id}/import",
        response_model=DocxMetadata,
        responses=errors,
        dependencies=[Depends(import_query)],
        openapi_extra=body_schema,
    )
    async def upload(
        document_id: HttpUUID,
        request: Request,
        response: Response,
        title: str = Query(..., min_length=1, max_length=200),
    ):
        data = await read_upload(request)
        result = await run_in_threadpool(
            perform, import_docx, document_id=document_id, title=title, data=data
        )
        response.headers["Cache-Control"] = "no-store"
        return result

    @router.put(
        "/docx-documents/{document_id}/content",
        response_model=DocxMetadata,
        responses=errors,
        dependencies=[Depends(save_query)],
        openapi_extra=body_schema,
    )
    async def save(
        document_id: HttpUUID,
        request: Request,
        response: Response,
        expected_storage_revision: int = Query(..., ge=1, le=MAX_REVISION - 1),
    ):
        data = await read_upload(request)
        result = await run_in_threadpool(
            perform,
            save_docx,
            document_id=document_id,
            expected_storage_revision=expected_storage_revision,
            data=data,
        )
        response.headers["Cache-Control"] = "no-store"
        return result

    app.include_router(router)
    previous_openapi = app.openapi

    def writes_openapi():
        schema = previous_openapi()
        operation = schema["paths"]["/docx-documents/{document_id}/content"]["put"]
        for parameter in operation["parameters"]:
            if parameter["name"] == "expected_storage_revision":
                parameter["schema"]["maximum"] = MAX_REVISION - 1
        return schema

    app.openapi = writes_openapi
