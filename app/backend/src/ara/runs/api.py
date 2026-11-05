"""Local routes sharing document authentication context and safe error handlers."""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, FastAPI, Header

from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError
from ara.runs.schemas import CreateRun, RunResponse
from ara.runs.storage import create_run, read_run


def install_runs(app: FastAPI, runtime: DocumentRuntime) -> None:
    router = APIRouter()

    @router.post("/documents/{document_id}/runs", status_code=202, response_model=RunResponse)
    def enqueue(
        document_id: UUID,
        body: CreateRun,
        idempotency_key: Annotated[list[str], Header()],
    ):
        if (
            len(idempotency_key) != 1
            or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key[0]) is None
        ):
            raise DocumentError(422, "validation_error", "Invalid request")
        return create_run(runtime, document_id, body, idempotency_key[0])

    @router.get("/runs/{run_id}", response_model=RunResponse)
    def get_run(run_id: UUID):
        return read_run(runtime, run_id)

    app.include_router(router)
