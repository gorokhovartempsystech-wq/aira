"""Bounded ASGI input and a nonblocking per-app transport admission gate."""

import json
import re
from threading import BoundedSemaphore
from uuid import uuid4


def invalid():
    from ._errors import error

    error("validation_error", 422)


def _unsupported():
    from ara.documents.storage import DocumentError

    raise DocumentError(415, "unsupported_media_type", "Unsupported editor media type")


def _large():
    from ara.documents.storage import DocumentError

    raise DocumentError(413, "editor_request_too_large", "Editor request exceeds a technical limit")


async def read_body(request, maximum, *, require_json=True):
    from starlette.requests import ClientDisconnect

    if request.scope.get("query_string", b""):
        invalid()
    headers = {}
    for name, value in request.scope.get("headers", []):
        headers.setdefault(name.lower(), []).append(value.decode("latin-1"))
    for key in (b"content-type", b"content-length", b"content-encoding", b"transfer-encoding"):
        if len(headers.get(key, [])) > 1:
            invalid()

    def header(name, default=None):
        return headers.get(name, [default])[0]

    media = header(b"content-type")
    if require_json or media is not None:
        parts = (media or "").lower().split(";")
        if (
            parts[0].strip() != "application/json"
            or len(parts) > 2
            or (len(parts) == 2 and parts[1].strip().replace(" ", "") != "charset=utf-8")
        ):
            _unsupported()
    if header(b"content-encoding", "identity").strip().lower() != "identity":
        _unsupported()
    length, transfer = header(b"content-length"), header(b"transfer-encoding")
    if transfer is not None:
        if length is not None or transfer.strip().lower() != "chunked":
            invalid()
    if length is not None:
        if len(length) > 19 or re.fullmatch(r"[0-9]+", length) is None:
            invalid()
        length = int(length)
        if maximum == 0 and length:
            invalid()
        if length > maximum:
            _large()
    data = bytearray()
    try:
        async for chunk in request.stream():
            if maximum == 0 and chunk:
                invalid()
            if len(data) + len(chunk) > maximum:
                _large()
            data.extend(chunk)
    except ClientDisconnect:
        invalid()
    if length is not None and len(data) != length:
        invalid()
    return bytes(data)


def load_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Invalid JSON constant")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError):
        invalid()


class EditorTransport:
    def __init__(self, app):
        self.app = app
        self.gate = BoundedSemaphore(1)

    async def __call__(self, scope, receive, send):
        from starlette.datastructures import MutableHeaders
        from starlette.responses import JSONResponse

        target = (
            scope["type"] == "http"
            and re.fullmatch(
                r"/docx-documents/[^/]+/editor-(?:recovery|sessions)(?:/.*)?", scope["path"]
            )
            is not None
        )
        if not target:
            await self.app(scope, receive, send)
            return

        async def guarded(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        if not self.gate.acquire(blocking=False):
            response = JSONResponse(
                status_code=503,
                content=dict(
                    code="editor_busy",
                    message="Editor is handling another request",
                    retryable=True,
                    request_id=str(uuid4()),
                ),
                headers={"Cache-Control": "no-store", "X-ARA-Auth-Mode": "local-dev"},
            )
            await response(scope, receive, guarded)
            return
        try:
            await self.app(scope, receive, guarded)
        finally:
            self.gate.release()
