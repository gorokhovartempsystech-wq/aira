"""Bounded working copy HTTP operations, installed only with a local runtime."""


def install_recovery(app, runtime):
    import json
    import re

    from fastapi import APIRouter, Request, Response
    from pydantic import ValidationError
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import ClientDisconnect

    from ara.documents.storage import DocumentError
    from ara.docx_documents.recovery import recover
    from ara.docx_documents.recovery_schemas import (
        DeleteRecovery,
        PutRecovery,
        RecoveryEnvelope,
    )
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID

    maximum = 2 * 1024 * 1024

    def invalid():
        raise DocumentError(422, "validation_error", "Invalid request")

    def too_large():
        raise DocumentError(
            413, "draft_request_too_large", "Document draft request exceeds a technical limit"
        )

    def unsupported():
        raise DocumentError(415, "unsupported_media_type", "Unsupported draft media type")

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
        raise ValueError("Invalid constant")

    def perform(document_id, data=None, deleting=False):
        body = None
        if data is not None:
            try:
                decoded = json.loads(
                    data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
                )
                body = (DeleteRecovery if deleting else PutRecovery).model_validate(decoded)
            except (ValueError, ValidationError, RecursionError):
                invalid()
        return recover(runtime, document_id, body, deleting=deleting)

    errors = {
        status: {"model": DraftErrorResponse} for status in (404, 409, 413, 415, 422, 500, 503)
    }
    router = APIRouter()
    url = "/docx-documents/{document_id}/draft"

    @router.get(url, response_model=RecoveryEnvelope, responses=errors)
    async def get_draft(document_id: HttpUUID, request: Request, response: Response):
        if request.query_params:
            invalid()
        result = await run_in_threadpool(perform, document_id)
        response.headers["Cache-Control"] = "no-store"
        return result

    def request_schema(name):
        return {
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + name}}
                },
            }
        }

    @router.put(
        url,
        response_model=RecoveryEnvelope,
        responses=errors,
        openapi_extra=request_schema("PutRecovery"),
    )
    async def put_draft(document_id: HttpUUID, request: Request, response: Response):
        if request.query_params:
            invalid()
        data = await read_body(request)
        result = await run_in_threadpool(perform, document_id, data)
        response.headers["Cache-Control"] = "no-store"
        return result

    @router.delete(
        url, status_code=204, responses=errors, openapi_extra=request_schema("DeleteRecovery")
    )
    async def delete_draft(document_id: HttpUUID, request: Request):
        if request.query_params:
            invalid()
        data = await read_body(request)
        await run_in_threadpool(perform, document_id, data, True)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    app.include_router(router)
    previous_openapi = app.openapi

    def recovery_openapi():
        schema = previous_openapi()
        for model in (PutRecovery, DeleteRecovery):
            definition = model.model_json_schema(ref_template="#/components/schemas/{model}")
            schema["components"]["schemas"].update(definition.pop("$defs", {}))
            schema["components"]["schemas"][model.__name__] = definition
        return schema

    app.openapi = recovery_openapi
