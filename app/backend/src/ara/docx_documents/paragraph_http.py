"""Bounded paragraph command transport installed only with an explicit runtime."""


def install_paragraph_commands(app, runtime):
    import json
    import re
    from uuid import UUID

    from fastapi import APIRouter, Request, Response
    from starlette.concurrency import run_in_threadpool
    from starlette.datastructures import MutableHeaders
    from starlette.requests import ClientDisconnect

    from ara.documents.storage import DocumentError
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID

    from .paragraph_schemas import ParagraphCommandReceipt, ParagraphCommandsRequest
    from .paragraph_storage import save_commands

    maximum = 2 * 1024 * 1024

    class CommandNoStore:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            target = (
                scope["type"] == "http"
                and scope["method"] == "POST"
                and re.fullmatch(
                    r"/docx-documents/[^/]+/(paragraph-commands|text-edit)", scope["path"]
                )
                is not None
            )

            async def guarded_send(message):
                if target and message["type"] == "http.response.start":
                    MutableHeaders(scope=message)["Cache-Control"] = "no-store"
                await send(message)

            await self.app(scope, receive, guarded_send)

    # Both entry points share the retry ledger, including cross-kind conflicts.
    app.add_middleware(CommandNoStore)

    def invalid():
        raise DocumentError(422, "validation_error", "Invalid request")

    def unsupported():
        raise DocumentError(415, "unsupported_media_type", "Unsupported edit media type")

    def too_large():
        raise DocumentError(
            413, "edit_request_too_large", "DOCX edit request exceeds a technical limit"
        )

    async def read_body(request):
        for name in ("content-type", "content-encoding", "content-length"):
            if len(request.headers.getlist(name)) > 1:
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
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Invalid JSON constant")

    def perform(document_id, operation_id, data):
        try:
            decoded = json.loads(
                data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
            )
            body = ParagraphCommandsRequest.model_validate(decoded)
        except (ValueError, RecursionError):
            invalid()
        try:
            saved = save_commands(
                runtime, document_id=document_id, operation_id=operation_id, body=body
            )
            return ParagraphCommandReceipt(
                operation_id=operation_id,
                document_id=saved.document_id,
                title=saved.title,
                storage_revision=str(saved.storage_revision),
                current_sha256=saved.current_sha256,
                current_size_bytes=saved.current_size_bytes,
                created_at=saved.created_at,
                updated_at=saved.updated_at,
            )
        except DocumentError:
            raise
        except Exception:
            raise DocumentError(500, "storage_error", "Document storage operation failed") from None

    router = APIRouter()

    @router.post(
        "/docx-documents/{document_id}/paragraph-commands",
        response_model=ParagraphCommandReceipt,
        responses={
            status: {"model": DraftErrorResponse} for status in (404, 409, 413, 415, 422, 500, 503)
        },
        openapi_extra={
            "parameters": [
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "description": "Canonical lowercase UUID for one exact paragraph batch",
                    "schema": {"type": "string", "format": "uuid"},
                }
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ParagraphCommandsRequest"}
                    }
                },
            },
        },
    )
    async def commands(document_id: HttpUUID, request: Request, response: Response):
        if request.query_params:
            invalid()
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1:
            invalid()
        try:
            operation_id = UUID(keys[0])
        except ValueError:
            invalid()
        if str(operation_id) != keys[0]:
            invalid()
        data = await read_body(request)
        result = await run_in_threadpool(perform, document_id, operation_id, data)
        response.headers["Cache-Control"] = "no-store"
        return result

    app.include_router(router)
    previous_openapi = app.openapi

    def commands_openapi():
        schema = previous_openapi()
        request_schema = ParagraphCommandsRequest.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions = request_schema.pop("$defs", {})
        schema["components"]["schemas"].update(definitions)
        schema["components"]["schemas"]["ParagraphCommandsRequest"] = request_schema
        return schema

    app.openapi = commands_openapi
