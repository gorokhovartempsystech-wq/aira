"""Review routes installed only with an explicit local document runtime."""

from uuid import UUID

from fastapi import APIRouter, FastAPI

from ara.documents.runtime import DocumentRuntime
from ara.reviews.schemas import PutReview, ReviewResponse
from ara.reviews.storage import read_review, save_review


def install_reviews(app: FastAPI, runtime: DocumentRuntime) -> None:
    router = APIRouter()

    @router.get("/runs/{run_id}/review", response_model=ReviewResponse)
    def get_review(run_id: UUID, revision_id: UUID | None = None):
        return read_review(runtime, run_id, revision_id=revision_id)

    @router.put("/runs/{run_id}/review", response_model=ReviewResponse)
    def put_review(run_id: UUID, body: PutReview):
        return save_review(runtime, run_id, body)

    app.include_router(router)
