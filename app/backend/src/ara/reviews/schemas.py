"""Strict review wire shapes, preserving proposal text verbatim."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from ara.analysis_contract.models import Nonblank, Text

Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class TextEdit(ReviewModel):
    patch_index: int = Field(ge=0)
    new_block_index: int = Field(ge=0)
    text: Text


class GroupDecision(ReviewModel):
    group_id: Nonblank
    decision: Literal["pending", "accepted", "rejected", "deferred"]
    edits: list[TextEdit] = Field(max_length=5000)

    @model_validator(mode="after")
    def unique_edits(self) -> Self:
        indices = [(edit.patch_index, edit.new_block_index) for edit in self.edits]
        if len(indices) != len(set(indices)):
            raise ValueError("Duplicate edit indices")
        return self


class PutReview(ReviewModel):
    expected_revision_id: str | None = Field(json_schema_extra={"format": "uuid"})
    expected_result_fingerprint: Fingerprint
    decisions: list[GroupDecision] = Field(max_length=5000)

    @field_validator("expected_revision_id")
    @classmethod
    def canonical_revision(cls, value: str | None) -> str | None:
        return str(UUID(value)) if value is not None else None

    @model_validator(mode="after")
    def limits_and_groups(self) -> Self:
        ids = [decision.group_id for decision in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate group identifiers")
        if sum(len(decision.edits) for decision in self.decisions) > 5000:
            raise ValueError("Too many edits")
        if (
            sum(len(edit.text) for decision in self.decisions for edit in decision.edits)
            > 1_000_000
        ):
            raise ValueError("Edits are too large")
        return self


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    document_id: UUID
    base_version_id: UUID
    context_revision_id: UUID
    execution_mode: Literal["fixture"]
    revision_id: UUID | None
    parent_revision_id: UUID | None
    revision_number: int = Field(ge=0)
    created_at: AwareDatetime | None
    result_fingerprint: Fingerprint
    decisions: list[GroupDecision]
