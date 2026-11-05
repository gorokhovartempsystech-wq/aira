"""One optional router sharing analysis admission and its finite runtime pool."""


def install(app):
    from typing import Annotated
    from uuid import UUID

    import anyio
    from fastapi import APIRouter, Request
    from pydantic import BeforeValidator, WithJsonSchema
    from starlette.responses import JSONResponse

    from ara.config import ConfigurationError
    from ara.documents.runtime import DocumentRuntime
    from ara.documents.storage import DocumentError
    from ara.docx_analysis_api import _wire as analysis_wire
    from ara.docx_analysis_api._service import Service
    from ara.docx_editor._http_transport import load_json, read_body
    from ara.docx_review_commands import clear_hidden, set_hidden
    from ara.docx_review_preferences import get_state, set_preferences
    from ara.docx_review_preferences._models import fail

    from . import _view, _wire

    service = getattr(app.state, "docx_analysis_service", None)
    if (
        hasattr(app.state, "docx_review_installed")
        or type(service) is not Service
        or type(service.runtime) is not DocumentRuntime
        or getattr(app.state, "docx_editor_registry", None) is not service.registry
    ):
        raise ConfigurationError("Review requires one installed analysis service and editor")
    limiter = anyio.CapacityLimiter(2)
    path_uuid = Annotated[
        UUID,
        BeforeValidator(analysis_wire.uuid),
        WithJsonSchema(dict(type="string", format="uuid")),
    ]
    path_finding = Annotated[
        str,
        BeforeValidator(_wire.finding),
        WithJsonSchema(dict(type="string", pattern="^df-[0-9a-f]{64}$")),
    ]

    def perform(operation, document_id, run_id, finding_id, data):
        try:
            if operation == "get":
                return dict(
                    schema_version=_wire.VERSION,
                    preferences=_wire.preferences(
                        get_state(service.runtime, document_id=document_id)
                    ),
                )
            if operation == "review":
                return _view.get_review(service.runtime, document_id, run_id)
            if operation == "clear":
                return _wire.receipt(
                    clear_hidden(
                        service.runtime,
                        document_id=document_id,
                        **_wire.clear_command(load_json(data)),
                    )
                )
            values = _wire.command(load_json(data), visibility=operation == "visibility")
            if operation == "visibility":
                result = set_hidden(
                    service.runtime,
                    document_id=document_id,
                    run_id=run_id,
                    finding_id=finding_id,
                    **values,
                )
            else:
                result = set_preferences(service.runtime, document_id=document_id, **values)
            return _wire.receipt(result)
        except DocumentError:
            raise
        except Exception:
            fail("storage_error")

    async def dispatch(
        request, operation, document_id, run_id=None, finding_id=None, *, post=False
    ):
        data = await read_body(request, 65536 if post else 0, require_json=post)
        with anyio.CancelScope(shield=True):
            output = await anyio.to_thread.run_sync(
                perform, operation, document_id, run_id, finding_id, data, limiter=limiter
            )
        return JSONResponse(output, headers={"Cache-Control": "no-store"})

    router = APIRouter()
    prefix = "/docx-documents/{document_id}"

    @router.get(prefix + "/analysis-preferences", openapi_extra=_wire.schema("get"))
    async def get(document_id: path_uuid, request: Request):
        return await dispatch(request, "get", document_id)

    @router.post(prefix + "/analysis-preferences", openapi_extra=_wire.schema("preferences"))
    async def preferences(document_id: path_uuid, request: Request):
        return await dispatch(request, "preferences", document_id, post=True)

    @router.post(prefix + "/analysis-preferences/clear-hidden", openapi_extra=_wire.schema("clear"))
    async def clear(document_id: path_uuid, request: Request):
        return await dispatch(request, "clear", document_id, post=True)

    @router.post(
        prefix + "/analysis-runs/{run_id}/findings/{finding_id}/visibility",
        openapi_extra=_wire.schema("visibility"),
    )
    async def visibility(
        document_id: path_uuid, run_id: path_uuid, finding_id: path_finding, request: Request
    ):
        return await dispatch(request, "visibility", document_id, run_id, finding_id, post=True)

    @router.get(prefix + "/analysis-runs/{run_id}/review", openapi_extra=_wire.schema("review"))
    async def review(document_id: path_uuid, run_id: path_uuid, request: Request):
        return await dispatch(request, "review", document_id, run_id)

    @router.get(prefix + "/analysis-review", openapi_extra=_wire.schema("review"))
    async def latest(document_id: path_uuid, request: Request):
        return await dispatch(request, "review", document_id)

    app.include_router(router)
    app.state.docx_review_installed = True
