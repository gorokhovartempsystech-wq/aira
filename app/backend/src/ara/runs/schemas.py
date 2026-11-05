"""Strict enqueue boundary and explicit persisted-run response."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from ara.analysis_contract.models import AnalysisRequest, AnalysisResult, ContextItem, Nonblank


class RunContextItem(ContextItem):
    id: Annotated[Nonblank, Field(max_length=200)]
    text: Nonblank


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["lint", "merge"]
    base_version_id: str = Field(json_schema_extra={"format": "uuid"})
    context_items: list[RunContextItem] = Field(max_length=100)

    @field_validator("base_version_id")
    @classmethod
    def canonical_version(cls, value: str) -> str:
        return str(UUID(value))

    @model_validator(mode="after")
    def valid_context(self) -> Self:
        ids = [item.id for item in self.context_items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate context identifiers")
        if sum(len(item.text) for item in self.context_items) > 1_000_000:
            raise ValueError("Context is too large")
        has_new = any(item.role == "new_requirement" for item in self.context_items)
        if has_new != (self.mode == "merge"):
            raise ValueError("Context does not match mode")
        return self


class RunError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "deadline_exceeded",
        "attempts_exhausted",
        "access_revoked",
        "invalid_request",
        "invalid_result",
    ]
    message: str
    retryable: Literal[False] = False


class RunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    document_id: UUID
    base_version_id: UUID
    context_revision_id: UUID
    mode: Literal["lint", "merge"]
    status: Literal["queued", "running", "succeeded", "failed"]
    execution_mode: Literal["fixture"]
    created_at: AwareDatetime
    request: AnalysisRequest
    has_import_omissions: bool
    attempt_count: int
    result: AnalysisResult | None
    incomplete_review: bool | None
    error: RunError | None
