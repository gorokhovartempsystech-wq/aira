"""Deferred binary transport using the existing app-owned registry and gate."""


def install_editor_downloads(app):
    from typing import Annotated
    from uuid import UUID

    import anyio
    from fastapi import APIRouter, Request, Response
    from pydantic import BeforeValidator, WithJsonSchema
    from starlette.concurrency import run_in_threadpool

    from ara.config import ConfigurationError

    from . import wire
    from ._download_schema import MIME, extra, install_schema
    from ._http_transport import load_json, read_body

    if not hasattr(app.state, "docx_editor_registry") or getattr(
        app.state, "docx_editor_downloads_installed", False
    ):
        raise ConfigurationError("Editor downloads require one installed registry")
    registry = app.state.docx_editor_registry
    path_uuid = Annotated[
        UUID, BeforeValidator(wire._uuid), WithJsonSchema(dict(type="string", format="uuid"))
    ]

    def perform(operation, document_id, session_id, data):
        from ara.documents.storage import DocumentError
        from ara.docx_documents._dto import _hash

        from ._errors import validate

        try:
            body = load_json(data)
            if operation == "saved":
                target = registry.saved_target(
                    document_id=document_id, session_id=session_id, **wire.decode_control(body)
                )
                headers = {"X-ARA-Storage-Revision": str(target.storage_revision)}
            else:
                counters = (
                    ("expected_command_sequence", "expected_session_revision")
                    if operation == "working"
                    else ("expected_checkpoint_revision",)
                )
                wire._shape(body, (*counters, "expected_sha256"))
                validate(_hash(body["expected_sha256"]))
                kwargs = {key: wire._counter(body[key]) for key in counters}
                kwargs["expected_sha256"] = body["expected_sha256"]
                if operation == "working":
                    target = registry.working_target(
                        document_id=document_id, session_id=session_id, **kwargs
                    )
                    headers = {
                        "X-ARA-Command-Sequence": str(target.command_sequence),
                        "X-ARA-Session-Revision": str(target.session_revision),
                    }
                else:
                    target = registry.recovery_target(document_id=document_id, **kwargs)
                    headers = {"X-ARA-Checkpoint-Revision": str(target.checkpoint_revision)}
            suffix = "" if operation == "saved" else "-" + operation
            headers.update(
                {
                    "Cache-Control": "no-store",
                    "ETag": '"' + target.sha256 + '"',
                    "X-ARA-Copy-Kind": operation,
                    "Content-Disposition": f'attachment; filename="{document_id}{suffix}.docx"',
                }
            )
            return Response(target.data, media_type=MIME, headers=headers)
        except DocumentError:
            raise
        except Exception:
            raise DocumentError(500, "editor_error", "Editor operation failed") from None

    def handler(operation, *, recovery=False):
        async def dispatch(request, document_id, session_id):
            data = await read_body(request, 65536)
            with anyio.CancelScope(shield=True):
                return await run_in_threadpool(perform, operation, document_id, session_id, data)

        if recovery:

            async def endpoint(document_id: path_uuid, request: Request):
                return await dispatch(request, document_id, None)
        else:

            async def endpoint(document_id: path_uuid, session_id: path_uuid, request: Request):
                return await dispatch(request, document_id, session_id)

        return endpoint

    router = APIRouter()
    prefix = "/docx-documents/{document_id}"
    for operation in ("saved", "working", "recovery"):
        route = prefix + (
            "/editor-recovery/content"
            if operation == "recovery"
            else "/editor-sessions/{session_id}/" + operation + "-content"
        )
        router.add_api_route(
            route,
            handler(operation, recovery=operation == "recovery"),
            methods=["POST"],
            response_class=Response,
            name="editor_" + operation + "_content",
            openapi_extra=extra(operation),
        )
    app.include_router(router)
    install_schema(app)
    app.state.docx_editor_downloads_installed = True
