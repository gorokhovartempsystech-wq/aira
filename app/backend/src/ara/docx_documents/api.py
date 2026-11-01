"""Read-only DOCX transport; dependencies are loaded only during explicit setup."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ara.documents.runtime import DocumentRuntime


def install_docx_reads(app: "FastAPI", runtime: "DocumentRuntime") -> None:
    import re
    from dataclasses import asdict

    from fastapi import APIRouter, Depends, Query, Request, Response

    from ara.documents.storage import DocumentError
    from ara.docx_documents import get_docx, list_docx
    from ara.docx_documents.http_schemas import MAX_REVISION, DocxList, DocxMetadata
    from ara.drafts.http_schemas import DraftErrorResponse, HttpUUID

    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    errors = {
        code: {"model": DraftErrorResponse, "description": description}
        for code, description in (
            (404, "Document not found"),
            (422, "Invalid request"),
            (500, "Document storage operation failed"),
            (503, "Document storage is unavailable"),
        )
    }

    def invalid():
        raise DocumentError(422, "validation_error", "Invalid request")

    def list_query(request: Request):
        seen = set()
        for key, value in request.query_params.multi_items():
            if key not in ("limit", "offset") or key in seen:
                invalid()
            seen.add(key)
            if len(value) > 19 or re.fullmatch(r"[0-9]+", value) is None:
                invalid()
            lower, upper = (1, 100) if key == "limit" else (0, MAX_REVISION)
            if not lower <= int(value) <= upper:
                invalid()

    def no_query(request: Request):
        if request.query_params:
            invalid()

    def metadata(snapshot):
        return {
            "document_id": snapshot.document_id,
            "title": snapshot.title,
            "storage_revision": snapshot.storage_revision,
            "current_sha256": snapshot.current_sha256,
            "current_size_bytes": len(snapshot.current_data),
            "created_at": snapshot.created_at,
            "updated_at": snapshot.updated_at,
        }

    router = APIRouter()

    @router.get(
        "/docx-documents",
        response_model=DocxList,
        responses=errors,
        dependencies=[Depends(list_query)],
    )
    def read_list(
        response: Response,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=MAX_REVISION),
    ):
        items = list_docx(runtime, limit=limit, offset=offset)
        response.headers["Cache-Control"] = "no-store"
        return {"items": [asdict(item) for item in items]}

    @router.get(
        "/docx-documents/{document_id}",
        response_model=DocxMetadata,
        responses=errors,
        dependencies=[Depends(no_query)],
    )
    def read_metadata(document_id: HttpUUID, response: Response):
        result = get_docx(runtime, document_id=document_id)
        response.headers["Cache-Control"] = "no-store"
        return metadata(result)

    @router.get(
        "/docx-documents/{document_id}/content",
        response_class=Response,
        responses={
            **errors,
            200: {
                "content": {
                    mime: {
                        "schema": {
                            "type": "string",
                            "format": "binary",
                        }
                    }
                }
            },
        },
        dependencies=[Depends(no_query)],
    )
    def read_content(document_id: HttpUUID):
        result = get_docx(runtime, document_id=document_id)
        return Response(
            result.current_data,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="{result.document_id}.docx"',
                "ETag": f'"{result.current_sha256}"',
                "X-ARA-Storage-Revision": str(result.storage_revision),
                "Cache-Control": "no-store",
            },
        )

    app.include_router(router)
    previous_openapi = app.openapi

    def docx_openapi():
        schema = previous_openapi()
        fields = DocxMetadata.model_json_schema()["properties"]
        for name in ("storage_revision", "current_size_bytes"):
            schema["components"]["schemas"]["DocxMetadata"]["properties"][name] = fields[name]
        for parameter in schema["paths"]["/docx-documents"]["get"]["parameters"]:
            if parameter["name"] == "offset":
                parameter["schema"]["maximum"] = MAX_REVISION
        return schema

    app.openapi = docx_openapi
