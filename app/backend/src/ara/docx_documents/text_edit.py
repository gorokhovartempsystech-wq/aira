"""Bounded single-span edits using unchanged export and final storage CAS."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ara.documents.runtime import DocumentRuntime


def install_text_edit(app: "FastAPI", runtime: "DocumentRuntime") -> None:
    import json
    import re
    from uuid import UUID

    from fastapi import APIRouter, Request, Response
    from pydantic import ValidationError
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import ClientDisconnect

    from ara.documents.storage import DocumentError
    from ara.docx_documents import get_docx, save_docx
    from ara.docx_documents.text_edit_schemas import TextEditReceipt, TextEditRequest
    from ara.docx_package import DocxError
    from ara.docx_package.editing import EditError, TextEdit, export_docx
    from ara.docx_package.projection import ProjectionError, SourceAnchor
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID

    maximum = 2 * 1024 * 1024

    def invalid():
        raise DocumentError(422, "validation_error", "Invalid request")

    def too_large():
        raise DocumentError(
            413, "edit_request_too_large", "DOCX edit request exceeds a technical limit"
        )

    def unsupported():
        raise DocumentError(415, "unsupported_media_type", "Unsupported edit media type")

    async def read_body(request):
        for key in ("content-type", "content-encoding", "content-length"):
            if len(request.headers.getlist(key)) > 1:
                invalid()
        media = request.headers.get("content-type", "").lower().split(";")
        if media[0].strip() != "application/json" or len(media) > 2:
            unsupported()
        if len(media) == 2 and media[1].strip().replace(" ", "") != "charset=utf-8":
            unsupported()
        if request.headers.get("content-encoding", "identity").strip().lower() != "identity":
            unsupported()
        length = request.headers.get("content-length")
        if length is not None:
            if "transfer-encoding" in request.headers:
                invalid()
            if len(length) > 19 or re.fullmatch(r"[0-9]+", length) is None:
                invalid()
            length = int(length)
            if length > maximum:
                too_large()
        data = bytearray()
        try:
            async for chunk in request.stream():
                if len(data) + len(chunk) > maximum:
                    too_large()
                data.extend(chunk)
        except ClientDisconnect:
            invalid()
        if length is not None and len(data) != length:
            invalid()
        return bytes(data)

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Invalid JSON constant")

    def perform(document_id, data, operation_id=None):
        try:
            decoded = json.loads(
                data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
            )
            body = TextEditRequest.model_validate(decoded)
        except (ValueError, ValidationError, RecursionError):
            invalid()
        try:
            if operation_id is not None:
                from ara.docx_documents.idempotent_edit import save_edit

                saved = save_edit(
                    runtime, document_id=document_id, operation_id=operation_id, body=body
                )
                return TextEditReceipt(
                    document_id=saved.document_id,
                    title=saved.title,
                    storage_revision=str(saved.storage_revision),
                    current_sha256=saved.current_sha256,
                    current_size_bytes=saved.current_size_bytes,
                    created_at=saved.created_at,
                    updated_at=saved.updated_at,
                )
            expected = int(body.expected_storage_revision)
            snapshot = get_docx(runtime, document_id=document_id)
            if snapshot.storage_revision != expected:
                raise DocumentError(409, "docx_conflict", "Document storage revision has changed")
            anchor = SourceAnchor(
                body.anchor.source_sha256, body.anchor.part_name, tuple(body.anchor.path)
            )
            data = export_docx(
                snapshot.current_data,
                (TextEdit(anchor, body.expected_text, body.replacement_text),),
            )
            # Re-check the same expected revision after potentially expensive
            # export. Another writer may have committed since the initial read.
            saved = save_docx(
                runtime, document_id=document_id, expected_storage_revision=expected, data=data
            )
            return TextEditReceipt(
                document_id=saved.document_id,
                title=saved.title,
                storage_revision=str(saved.storage_revision),
                current_sha256=saved.current_sha256,
                current_size_bytes=len(saved.current_data),
                created_at=saved.created_at,
                updated_at=saved.updated_at,
            )
        except DocumentError:
            raise
        except EditError as exc:
            status = 409 if exc.code in ("stale_source", "text_mismatch") else 422
            if exc.code == "edit_limit_exceeded":
                status = 413
            raise DocumentError(status, exc.code, exc.message) from None
        except (DocxError, ProjectionError) as exc:
            status = (
                413 if exc.code in ("package_limit_exceeded", "projection_limit_exceeded") else 422
            )
            raise DocumentError(status, exc.code, exc.message) from None
        except Exception:
            raise DocumentError(500, "storage_error", "Document storage operation failed") from None

    errors = {
        status: {"model": DraftErrorResponse} for status in (404, 409, 413, 415, 422, 500, 503)
    }
    router = APIRouter()

    @router.post(
        "/docx-documents/{document_id}/text-edit",
        response_model=TextEditReceipt,
        responses=errors,
        openapi_extra={
            "parameters": [
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": False,
                    "description": "Canonical lowercase UUID identifying one exact edit attempt",
                    "schema": {"type": "string", "format": "uuid"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/TextEditRequest"},
                    }
                },
            },
        },
    )
    async def edit_text(document_id: HttpUUID, request: Request, response: Response):
        if request.query_params:
            invalid()
        keys = request.headers.getlist("idempotency-key")
        operation_id = None
        if keys:
            if len(keys) != 1:
                invalid()
            try:
                operation_id = UUID(keys[0])
            except ValueError:
                invalid()
            if str(operation_id) != keys[0]:
                invalid()
        data = await read_body(request)
        result = await run_in_threadpool(perform, document_id, data, operation_id)
        response.headers["Cache-Control"] = "no-store"
        return result

    app.include_router(router)
    previous_openapi = app.openapi

    def edit_openapi():
        schema = previous_openapi()
        request_schema = TextEditRequest.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions = request_schema.pop("$defs", {})
        schema["components"]["schemas"].update(definitions)
        schema["components"]["schemas"]["TextEditRequest"] = request_schema
        return schema

    app.openapi = edit_openapi
