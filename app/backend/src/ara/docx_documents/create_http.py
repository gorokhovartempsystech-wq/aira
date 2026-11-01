"""Create a server-owned blank DOCX only during explicit local HTTP setup."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ara.documents.runtime import DocumentRuntime


def install_docx_creation(app: "FastAPI", runtime: "DocumentRuntime") -> None:
    import re
    from urllib.parse import parse_qsl

    from fastapi import APIRouter, Depends, Query, Request, Response
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import ClientDisconnect

    from ara.documents.storage import DocumentError
    from ara.docx_documents import import_docx
    from ara.docx_documents._dto import valid_title
    from ara.docx_documents.http_schemas import DocxMetadata
    from ara.docx_package import DocxError
    from ara.docx_package.creation import CreationError, create_docx
    from ara.docx_package.projection import ProjectionError
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID

    def invalid():
        raise DocumentError(422, "validation_error", "Invalid request")

    def validate_query(request: Request):
        try:
            raw = request.scope["query_string"].decode("ascii")
            if re.search(r"%(?![0-9a-fA-F]{2})", raw):
                invalid()
            items = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, errors="strict")
        except (UnicodeError, ValueError):
            invalid()
        if len(items) != 1 or items[0][0] != "title" or not valid_title(items[0][1]):
            invalid()

    async def empty_body(request):
        for name in ("content-type", "content-encoding", "content-length"):
            if len(request.headers.getlist(name)) > 1:
                invalid()
        if "transfer-encoding" in request.headers:
            invalid()
        if (
            request.headers.get("content-type", "").strip()
            or request.headers.get("content-encoding", "identity").strip().lower() != "identity"
        ):
            raise DocumentError(415, "unsupported_media_type", "Unsupported document media type")
        length = request.headers.get("content-length")
        if length is not None and (
            len(length) > 19 or re.fullmatch(r"[0-9]+", length) is None or int(length) != 0
        ):
            invalid()
        try:
            async for chunk in request.stream():
                if chunk:
                    invalid()
        except ClientDisconnect:
            invalid()

    def perform(document_id, title):
        try:
            data = create_docx()
        except (CreationError, DocxError, ProjectionError):
            raise DocumentError(500, "creation_error", "Document could not be created") from None
        try:
            result = import_docx(runtime, document_id=document_id, title=title, data=data)
        except DocumentError as error:
            if error.code == "import_conflict":
                raise DocumentError(
                    409, "creation_conflict", "New document does not match"
                ) from None
            raise
        return DocxMetadata(
            document_id=result.document_id,
            title=result.title,
            storage_revision=result.storage_revision,
            current_sha256=result.current_sha256,
            current_size_bytes=len(result.current_data),
            created_at=result.created_at,
            updated_at=result.updated_at,
        )

    router = APIRouter()

    @router.post(
        "/docx-documents/{document_id}/create",
        response_model=DocxMetadata,
        responses={
            status: {"model": DraftErrorResponse} for status in (404, 409, 415, 422, 500, 503)
        },
        dependencies=[Depends(validate_query)],
    )
    async def create(
        document_id: HttpUUID,
        request: Request,
        response: Response,
        title: str = Query(..., min_length=1, max_length=200),
    ):
        await empty_body(request)
        result = await run_in_threadpool(perform, document_id, title)
        response.headers["Cache-Control"] = "no-store"
        return result

    app.include_router(router)
