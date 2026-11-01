"""Deferred explicit installation of the editor JSON transport."""


def install_editor_json(app, runtime):
    from typing import Annotated
    from uuid import UUID

    import anyio
    from fastapi import APIRouter, Request, Response
    from pydantic import BeforeValidator, WithJsonSchema
    from starlette.concurrency import run_in_threadpool

    from ara.config import ConfigurationError

    from . import EditorRegistry, wire
    from ._deadlines import scoped_runtime
    from ._http_schema import extra, install_schema
    from ._http_transport import EditorTransport, load_json, read_body

    if hasattr(app.state, "docx_editor_registry"):
        raise ConfigurationError("Editor transport is already installed")
    registry = EditorRegistry(scoped_runtime(runtime))
    app.state.docx_editor_registry = registry
    app.add_middleware(EditorTransport)
    path_uuid = Annotated[
        UUID, BeforeValidator(wire._uuid), WithJsonSchema(dict(type="string", format="uuid"))
    ]

    def perform(operation, document_id, session_id=None, data=None):
        from ara.documents.storage import DocumentError

        try:
            body = load_json(data) if data is not None else None
            if operation == "recovery":
                result = registry.inspect_recovery(document_id=document_id)
            elif operation == "open":
                result = registry.open(document_id=document_id, **wire.decode_open(body))
            elif operation in ("metadata", "view"):
                result = registry.snapshot(document_id=document_id, session_id=session_id)
                if operation == "view":
                    return wire.encode_projection(result)
            elif operation == "commands":
                result = registry.command(
                    document_id=document_id, session_id=session_id, **wire.decode_command(body)
                )
            else:
                handlers = dict(
                    checkpoint=registry.checkpoint,
                    save=registry.save,
                    reconcile=registry.reconcile,
                    close=registry.close,
                )
                result = handlers[operation](
                    document_id=document_id,
                    session_id=session_id,
                    **wire.decode_control(body, close=operation == "close"),
                )
            return wire.encode_reply(result)
        except DocumentError:
            raise
        except Exception:
            raise DocumentError(500, "editor_error", "Editor operation failed") from None

    async def dispatch(request, operation, document_id, session_id=None, *, post=False):
        data = await read_body(
            request,
            8 * 1024 * 1024 if operation == "commands" else 65536 if post else 0,
            require_json=post,
        )
        with anyio.CancelScope(shield=True):
            encoded = await run_in_threadpool(
                perform, operation, document_id, session_id, data if post else None
            )
        return Response(
            encoded, media_type="application/json", headers={"Cache-Control": "no-store"}
        )

    router = APIRouter()
    prefix = "/docx-documents/{document_id}"

    @router.get(prefix + "/editor-recovery", openapi_extra=extra(response="Recovery"))
    async def recovery(document_id: path_uuid, request: Request):
        return await dispatch(request, "recovery", document_id)

    @router.post(prefix + "/editor-sessions", openapi_extra=extra("OpenRequest", "Opened"))
    async def opening(document_id: path_uuid, request: Request):
        return await dispatch(request, "open", document_id, post=True)

    base = prefix + "/editor-sessions/{session_id}"

    @router.get(base, openapi_extra=extra())
    async def metadata(document_id: path_uuid, session_id: path_uuid, request: Request):
        return await dispatch(request, "metadata", document_id, session_id)

    @router.get(base + "/view", openapi_extra=extra(response="Projection"))
    async def view(document_id: path_uuid, session_id: path_uuid, request: Request):
        return await dispatch(request, "view", document_id, session_id)

    def control_handler(operation):
        async def handler(document_id: path_uuid, session_id: path_uuid, request: Request):
            return await dispatch(request, operation, document_id, session_id, post=True)

        return handler

    for operation in ("commands", "checkpoint", "save", "reconcile", "close"):
        body = (
            "CommandRequest"
            if operation == "commands"
            else "CloseRequest"
            if operation == "close"
            else "ControlRequest"
        )
        response = (
            "Closed"
            if operation == "close"
            else "Control"
            if operation == "reconcile"
            else "Metadata"
        )
        router.add_api_route(
            base + "/" + operation,
            control_handler(operation),
            methods=["POST"],
            name="editor_" + operation,
            openapi_extra=extra(body, response),
        )
    app.include_router(router)
    install_schema(app)
