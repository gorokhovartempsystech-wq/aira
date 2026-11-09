"""Team mockup runtime: authored text to DOCX; imports stay source-preserving."""

from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ara.docx_documents import import_docx, save_docx
from ara.docx_package.creation import CreationError, NewParagraph, create_docx


class TextDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    document_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    expected_revision: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100000)


def install_editor(app, runtime):
    from urllib.parse import urlsplit

    @app.get("/editor", include_in_schema=False)
    def page():
        return asset("editor.html")

    def asset(name):
        mime = {
            "editor.html": "text/html",
            "editor.css": "text/css",
            "editor.js": "text/javascript",
        }
        if name not in mime:
            raise HTTPException(404)
        return Response(
            (Path(__file__).parent / "static" / name).read_bytes(),
            media_type=mime[name],
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'self'; style-src 'self'; script-src 'self'; "
                    "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                ),
            },
        )

    @app.get("/editor/assets/{name}", include_in_schema=False)
    def files(name: str):
        return asset(name)

    @app.post("/editor/documents")
    def save(body: TextDocument, request: Request):
        if urlsplit("http://" + request.headers.get("host", "")).hostname not in (
            "127.0.0.1",
            "localhost",
            "::1",
            "testserver",
        ):
            raise HTTPException(403)
        if request.headers.get("origin") not in (None, str(request.base_url).rstrip("/")):
            raise HTTPException(403)
        try:
            identity = UUID(body.document_id)
        except ValueError:
            raise HTTPException(422, "Invalid document id") from None
        lines = body.text.splitlines()
        if len(lines) > 1000:
            raise HTTPException(422, "At most 1000 paragraphs")
        try:
            data = create_docx(tuple(NewParagraph(line) for line in lines))
        except CreationError:
            raise HTTPException(422, "Invalid document text") from None
        if body.expected_revision is None:
            saved = import_docx(runtime, document_id=identity, title=body.title, data=data)
        else:
            saved = save_docx(
                runtime,
                document_id=identity,
                expected_storage_revision=int(body.expected_revision),
                data=data,
            )
        return {
            "document_id": str(saved.document_id),
            "storage_revision": str(saved.storage_revision),
            "current_sha256": saved.current_sha256,
        }
