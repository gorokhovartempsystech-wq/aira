"""Deferred JSON recovery discard using the existing app-owned registry/gate."""


def install_editor_discard(app):
    from typing import Annotated
    from uuid import UUID

    import anyio
    from fastapi import APIRouter, Request, Response
    from pydantic import BeforeValidator, WithJsonSchema
    from starlette.concurrency import run_in_threadpool

    from ara.config import ConfigurationError

    from . import _discard, _discard_wire, wire
    from ._discard_schema import extra, install_schema
    from ._http_transport import load_json, read_body

    if not hasattr(app.state, "docx_editor_registry") or getattr(
        app.state, "docx_editor_discard_installed", False
    ):
        raise ConfigurationError("Editor discard requires one installed registry")
    runtime = app.state.docx_editor_registry._runtime
    path_uuid = Annotated[
        UUID, BeforeValidator(wire._uuid), WithJsonSchema(dict(type="string", format="uuid"))
    ]

    def perform(action, document_id, data):
        from ara.documents.storage import DocumentError

        try:
            body = load_json(data)
            if action == "prepare-discard":
                return _discard.prepare(
                    runtime, document_id=document_id, **_discard_wire.decode_prepare(body)
                )
            return _discard.execute(runtime, **_discard_wire.decode_plan(body, document_id))
        except DocumentError:
            raise
        except Exception:
            raise DocumentError(500, "editor_error", "Editor operation failed") from None

    def handler(action):
        async def endpoint(document_id: path_uuid, request: Request):
            data = await read_body(request, 65536)
            with anyio.CancelScope(shield=True):
                encoded = await run_in_threadpool(perform, action, document_id, data)
            return Response(
                encoded, media_type="application/json", headers={"Cache-Control": "no-store"}
            )

        return endpoint

    router = APIRouter()
    for action in ("prepare-discard", "discard"):
        router.add_api_route(
            "/docx-documents/{document_id}/editor-recovery/" + action,
            handler(action),
            methods=["POST"],
            name="editor_" + action.replace("-", "_"),
            openapi_extra=extra(action),
        )
    app.include_router(router)
    install_schema(app)
    app.state.docx_editor_discard_installed = True
