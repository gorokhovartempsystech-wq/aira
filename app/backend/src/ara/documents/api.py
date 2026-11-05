"""Local document routes; all database work is scoped to a single request."""

from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.exceptions import HTTPException

from ara.documents.runtime import DocumentRuntime
from ara.documents.schemas import CreateDocument, DocumentList, DocumentSummary, VersionResponse
from ara.documents.storage import DocumentError as DocumentError
from ara.documents.storage import _manual_version, _not_found, _session
from ara.models import Document, DocumentVersion


def install_documents(app: FastAPI, runtime: DocumentRuntime) -> None:
    app.description = (
        "Local development API using a shared synthetic test user. "
        "This is not real authentication. X-ARA-Auth-Mode: local-dev."
    )

    @app.middleware("http")
    async def local_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-ARA-Auth-Mode"] = "local-dev"
        return response

    def error_response(request: Request, error: DocumentError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status,
            content={
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(DocumentError)
    async def document_error(request: Request, error: DocumentError):
        return error_response(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return error_response(request, DocumentError(422, "validation_error", "Invalid request"))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        if error.status_code == 404:
            safe_error = _not_found()
        elif error.status_code in (400, 422):
            safe_error = DocumentError(422, "validation_error", "Invalid request")
        else:
            safe_error = DocumentError(error.status_code, "request_error", "Request not allowed")
        return error_response(request, safe_error)

    router = APIRouter()

    @router.get("/me")
    def current_user() -> dict[str, str]:
        with _session(runtime):
            result = {
                "user_id": str(runtime.user_id),
                "project_id": str(runtime.project_id),
                "environment": runtime.mode,
                "auth_mode": "local-dev",
            }
        return result

    @router.post("/documents", status_code=201, response_model=DocumentSummary)
    def create_document(body: CreateDocument):
        with _session(runtime) as session:
            document = Document(project_id=runtime.project_id, title=body.title, source_url=None)
            session.add(document)
            session.flush()
            version = _manual_version(document.id, None, body.content_markdown)
            session.add(version)
            session.flush()
            document.current_version_id = version.id
            session.flush()
            result = DocumentSummary.model_validate(document)
        return result

    @router.get("/documents", response_model=DocumentList)
    def list_documents(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        with _session(runtime) as session:
            documents = session.scalars(
                select(Document)
                .where(Document.project_id == runtime.project_id)
                .order_by(Document.created_at.desc(), Document.id.desc())
                .limit(limit)
                .offset(offset)
            )
            result = DocumentList(
                items=[DocumentSummary.model_validate(document) for document in documents]
            )
        return result

    @router.get("/documents/{document_id}/versions/{version_id}", response_model=VersionResponse)
    def read_version(document_id: UUID, version_id: UUID):
        with _session(runtime) as session:
            version = session.scalar(
                select(DocumentVersion)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    Document.project_id == runtime.project_id,
                    Document.id == document_id,
                    DocumentVersion.id == version_id,
                )
            )
            if version is None:
                raise _not_found()
            result = VersionResponse.model_validate(version)
        return result

    app.include_router(router)
