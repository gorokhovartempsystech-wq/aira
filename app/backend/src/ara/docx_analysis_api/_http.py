"""Opt-in transport. Bootstrap owns supervisor start/shutdown and database setup."""


def install(app, runtime, supervisor):
    from contextlib import asynccontextmanager
    from typing import Annotated
    from uuid import UUID

    import anyio
    from fastapi import APIRouter, Request
    from pydantic import BeforeValidator, WithJsonSchema
    from starlette.responses import JSONResponse

    from ara.config import ConfigurationError
    from ara.documents.storage import DocumentError
    from ara.docx_analysis_worker.supervisor._runtime_models import SupervisorError
    from ara.docx_editor._http_transport import load_json, read_body

    from . import _reads, _wire
    from ._service import Service
    from ._transport import AnalysisTransport

    if hasattr(app.state, "docx_analysis_service") or not hasattr(
        app.state, "docx_editor_registry"
    ):
        raise ConfigurationError("Analysis requires one installed editor registry")
    service = Service(runtime, app.state.docx_editor_registry, supervisor)
    app.state.docx_analysis_service = service
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        try:
            async with previous_lifespan(application) as state:
                yield state
        finally:
            service.close()

    app.router.lifespan_context = lifespan
    app.add_middleware(AnalysisTransport)
    ordinary_limiter, stop_limiter = anyio.CapacityLimiter(2), anyio.CapacityLimiter(1)
    path_uuid = Annotated[
        UUID, BeforeValidator(_wire.uuid), WithJsonSchema(dict(type="string", format="uuid"))
    ]

    def perform(operation, document_id, identifier, data):
        try:
            body = load_json(data) if data is not None else None
            if operation == "start":
                key, cmd = _wire.saved(document_id, body)
                return service.admit(key, cmd)
            if operation == "retry":
                key, cmd = _wire.retry(document_id, identifier, body)
                return service.admit(key, cmd)
            if operation == "stop":
                _wire.shape(body, ())
                return service.stop(document_id, identifier)
            if operation == "receipt":
                return service.receipt(document_id, identifier)
            if operation == "run":
                return dict(
                    schema_version=_wire.VERSION,
                    run=_wire.run(*_reads.get_run(service.runtime, document_id, identifier)),
                )
            return _wire.result(*_reads.get_result(service.runtime, document_id, identifier))
        except DocumentError:
            raise
        except SupervisorError as error:
            status = 422 if error.code == "validation_error" else 503
            raise DocumentError(
                status, error.code, "Analysis runtime is unavailable", status == 503
            ) from None
        except Exception:
            raise DocumentError(500, "analysis_error", "Analysis operation failed") from None

    async def dispatch(request, operation, document_id, identifier=None, *, post=False):
        data = await read_body(request, 65536 if post else 0, require_json=post)
        with anyio.CancelScope(shield=True):
            output = await anyio.to_thread.run_sync(
                perform,
                operation,
                document_id,
                identifier,
                data if post else None,
                limiter=stop_limiter if operation == "stop" else ordinary_limiter,
            )
        headers = {"Cache-Control": "no-store"}
        if post:
            headers["Location"] = (
                f"/docx-documents/{document_id}/analysis-requests/{output['client_request_id']}"
            )
        return JSONResponse(output, status_code=202 if post else 200, headers=headers)

    router = APIRouter()
    prefix = "/docx-documents/{document_id}"

    @router.post(prefix + "/analysis-runs", status_code=202, openapi_extra=_wire.schema("start"))
    async def start(document_id: path_uuid, request: Request):
        return await dispatch(request, "start", document_id, post=True)

    @router.post(
        prefix + "/analysis-runs/{run_id}/retry",
        status_code=202,
        openapi_extra=_wire.schema("retry"),
    )
    async def retry(document_id: path_uuid, run_id: path_uuid, request: Request):
        return await dispatch(request, "retry", document_id, run_id, post=True)

    @router.get(
        prefix + "/analysis-requests/{client_request_id}", openapi_extra=_wire.schema("receipt")
    )
    async def receipt(document_id: path_uuid, client_request_id: path_uuid, request: Request):
        return await dispatch(request, "receipt", document_id, client_request_id)

    @router.post(
        prefix + "/analysis-requests/{client_request_id}/stop",
        status_code=202,
        openapi_extra=_wire.schema("stop"),
    )
    async def stop(document_id: path_uuid, client_request_id: path_uuid, request: Request):
        return await dispatch(request, "stop", document_id, client_request_id, post=True)

    @router.get(prefix + "/analysis-runs/{run_id}", openapi_extra=_wire.schema("run"))
    async def run(document_id: path_uuid, run_id: path_uuid, request: Request):
        return await dispatch(request, "run", document_id, run_id)

    @router.get(prefix + "/analysis-runs/{run_id}/result", openapi_extra=_wire.schema("result"))
    async def result(document_id: path_uuid, run_id: path_uuid, request: Request):
        return await dispatch(request, "result", document_id, run_id)

    @router.get(prefix + "/analysis-result", openapi_extra=_wire.schema("result"))
    async def latest(document_id: path_uuid, request: Request):
        return await dispatch(request, "result", document_id)

    app.include_router(router)

    from ara.docx_review_api import install_review

    install_review(app)
