"""Draft transport installed only with an explicit local document runtime."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ara.documents.runtime import DocumentRuntime


def install_drafts(app: "FastAPI", runtime: "DocumentRuntime") -> None:
    # HTTP dependencies and Pydantic schema building belong to explicit setup,
    # not to importing any module in the drafts package.
    from fastapi import APIRouter, Depends, Request

    from ara.documents.storage import DocumentError
    from ara.drafts import DraftSnapshot, read_draft, save_draft
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID, PutDraft

    errors = {
        404: {"model": DraftErrorResponse, "description": "Document or version not found"},
        422: {"model": DraftErrorResponse, "description": "Invalid request"},
        500: {"model": DraftErrorResponse, "description": "Document storage operation failed"},
        503: {"model": DraftErrorResponse, "description": "Document storage is unavailable"},
    }
    router = APIRouter()

    async def require_utf8_json(request: Request) -> None:
        raw = await request.body()
        try:
            raw.decode("utf-8")
            # Python's JSON decoder also auto-detects UTF-16/32. Reject their
            # NUL-padded syntax, which is never legal in a UTF-8 JSON body.
            # An escaped JSON NUL is separately rejected by text validation.
            if b"\x00" in raw:
                raise ValueError("Invalid JSON encoding")
        except ValueError:
            raise DocumentError(422, "validation_error", "Invalid request") from None

    @router.get(
        "/documents/{document_id}/draft",
        response_model=DraftSnapshot | None,
        responses=errors,
    )
    def get_draft(document_id: HttpUUID):
        return read_draft(runtime, document_id=document_id)

    @router.put(
        "/documents/{document_id}/draft",
        response_model=DraftSnapshot,
        dependencies=[Depends(require_utf8_json)],
        responses={
            **errors,
            409: {"model": DraftErrorResponse, "description": "Draft revision has changed"},
        },
    )
    def put_draft(document_id: HttpUUID, body: PutDraft):
        return save_draft(
            runtime,
            document_id=document_id,
            expected_revision=body.expected_revision,
            base_version_id=body.base_version_id,
            content_markdown=body.content_markdown,
        )

    app.include_router(router)

    original_openapi = app.openapi

    def draft_openapi():
        schema = original_openapi()
        # FastAPI's OpenAPI model coerces numeric bounds to float, rounding
        # BIGINT limits. Restore only the draft fields from their actual models.
        for model, field in ((PutDraft, "expected_revision"), (DraftSnapshot, "revision")):
            schema["components"]["schemas"][model.__name__]["properties"][field] = (
                model.model_json_schema()["properties"][field]
            )
        return schema

    app.openapi = draft_openapi
