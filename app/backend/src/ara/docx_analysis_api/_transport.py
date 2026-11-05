"""Separate nonwaiting HTTP admission for ordinary requests and Stop."""

import re
from threading import BoundedSemaphore
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse


class AnalysisTransport:
    def __init__(self, app):
        self.app = app
        self.gate, self.stop_gate = BoundedSemaphore(2), BoundedSemaphore(1)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or re.fullmatch(
                r"/docx-documents/[^/]+/analysis-(?:runs|requests|result|review|preferences)(?:/.*)?",
                path,
            )
            is None
        ):
            await self.app(scope, receive, send)
            return

        async def guarded(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        stop = (
            scope["method"] == "POST"
            and re.fullmatch(r"/docx-documents/[^/]+/analysis-requests/[^/]+/stop", path)
            is not None
        )
        gate = self.stop_gate if stop else self.gate
        if not gate.acquire(blocking=False):
            response = JSONResponse(
                status_code=503,
                content=dict(
                    code="analysis_busy",
                    message="Analysis is handling another request",
                    retryable=True,
                    request_id=str(uuid4()),
                ),
                headers={"X-ARA-Auth-Mode": "local-dev"},
            )
            await response(scope, receive, guarded)
            return
        try:
            await self.app(scope, receive, guarded)
        finally:
            gate.release()
