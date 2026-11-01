"""Strict wire models for contract 0.1.0; no runtime configuration or I/O."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _unicode_text(value: str) -> str:
    if "\x00" in value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("Invalid Unicode text")
    return value


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("A nonblank string is required")
    return value


# JSON Schema patterns mirror the string validators without normalizing text.
Text = Annotated[
    str,
    AfterValidator(_unicode_text),
    Field(json_schema_extra={"pattern": r"^[^\u0000\uD800-\uDFFF]*$"}),
]
Nonblank = Annotated[
    Text,
    AfterValidator(_nonblank),
    Field(
        min_length=1,
        json_schema_extra={"pattern": r"^(?=[\s\S]*\S)[^\u0000\uD800-\uDFFF]*$"},
    ),
]
Quote = Annotated[Text, Field(min_length=1)]
Source = Literal["base", "context"]
SupportedKind = Literal["heading", "paragraph", "list", "table", "code"]
BlockKind = Literal["heading", "paragraph", "list", "table", "code", "unsupported"]


def _unique(values: list) -> list:
    if len(values) != len(set(values)):
        raise ValueError("Duplicate identifiers")
    return values


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class Block(ContractModel):
    id: Nonblank
    kind: BlockKind
    text: Text


class BaseDocument(ContractModel):
    document_id: Nonblank
    version_id: Nonblank
    blocks: list[Block]

    @model_validator(mode="after")
    def unique_blocks(self) -> Self:
        _unique([block.id for block in self.blocks])
        return self


class ContextItem(ContractModel):
    id: Nonblank
    role: Literal["new_requirement", "user_clarification", "reference"]
    text: Text


class Context(ContractModel):
    revision_id: Nonblank
    items: list[ContextItem]

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        _unique([item.id for item in self.items])
        return self


class AnalysisRequest(ContractModel):
    contract_version: Literal["0.1.0"]
    run_id: Nonblank
    mode: Literal["lint", "merge"]
    base_document: BaseDocument
    context: Context

    @model_validator(mode="after")
    def requirements_match_mode(self) -> Self:
        has_new = any(item.role == "new_requirement" for item in self.context.items)
        if has_new != (self.mode == "merge"):
            raise ValueError("Context does not match analysis mode")
        return self


class Evidence(ContractModel):
    source: Source
    id: Nonblank
    quote: Quote


EvidenceList = Annotated[list[Evidence], Field(min_length=1)]


class CoverageEntry(ContractModel):
    source: Source
    id: Nonblank
    status: Literal["analyzed", "skipped"]
    reason: Nonblank | None

    @model_validator(mode="after")
    def reason_matches_status(self) -> Self:
        if (self.reason is None) != (self.status == "analyzed"):
            raise ValueError("Coverage reason does not match status")
        return self


class Finding(ContractModel):
    id: Nonblank
    category: Literal[
        "ambiguity", "contradiction", "duplication", "unverifiable", "contract_mismatch"
    ]
    severity: Literal["info", "warning", "critical"]
    assessment: Literal["observed_inconsistency", "needs_confirmation"]
    title: Nonblank
    explanation: Nonblank
    evidence: EvidenceList

    @model_validator(mode="after")
    def contradiction_fragments(self) -> Self:
        if self.category == "contradiction":
            fragments = {(item.source, item.id, item.quote) for item in self.evidence}
            if len(fragments) < 2:
                raise ValueError("Contradiction requires distinct fragments")
        return self


class NewBlock(ContractModel):
    kind: SupportedKind
    text: Text


class Patch(ContractModel):
    operation: Literal["replace_block", "insert_before", "insert_after", "delete_block"]
    target_block_id: Nonblank
    new_blocks: list[NewBlock]

    @model_validator(mode="after")
    def content_matches_operation(self) -> Self:
        if bool(self.new_blocks) == (self.operation == "delete_block"):
            raise ValueError("Patch content does not match operation")
        return self


IdReferences = Annotated[
    list[Nonblank],
    AfterValidator(_unique),
    Field(json_schema_extra={"uniqueItems": True}),
]


class ChangeGroup(ContractModel):
    id: Nonblank
    title: Nonblank
    basis: Literal["explicit_requirement", "design_proposal"]
    rationale: Nonblank
    evidence: EvidenceList
    depends_on_group_ids: IdReferences
    blocking_question_ids: IdReferences
    patches: Annotated[list[Patch], Field(min_length=1)]


class Question(ContractModel):
    id: Nonblank
    prompt: Nonblank
    reason: Nonblank
    evidence: EvidenceList


class ChangeOutcome(ContractModel):
    context_item_id: Nonblank
    status: Literal["proposed", "already_satisfied", "needs_clarification", "out_of_scope"]
    rationale: Nonblank
    change_group_ids: IdReferences
    question_ids: IdReferences
    evidence: list[Evidence]

    @model_validator(mode="after")
    def status_support(self) -> Self:
        if self.status == "proposed" and not self.change_group_ids:
            raise ValueError("Proposed outcome requires a group")
        if self.status == "already_satisfied" and not any(
            item.source == "base" for item in self.evidence
        ):
            raise ValueError("Satisfied outcome requires base evidence")
        if self.status == "needs_clarification" and not self.question_ids:
            raise ValueError("Clarification outcome requires a question")
        return self


class AnalysisResult(ContractModel):
    contract_version: Literal["0.1.0"]
    run_id: Nonblank
    base_version_id: Nonblank
    context_revision_id: Nonblank
    review_status: Literal["ready", "needs_clarification"]
    summary: Nonblank
    coverage: list[CoverageEntry]
    findings: list[Finding]
    change_groups: list[ChangeGroup]
    questions: list[Question]
    change_outcomes: list[ChangeOutcome]

    @model_validator(mode="after")
    def identities_and_status(self) -> Self:
        for collection in (self.findings, self.change_groups, self.questions):
            _unique([item.id for item in collection])
        if bool(self.questions) != (self.review_status == "needs_clarification"):
            raise ValueError("Review status does not match questions")
        return self


class ValidatedAnalysis(ContractModel):
    """Backend envelope; incomplete_review is never accepted in the ML result."""

    result: AnalysisResult
    incomplete_review: bool
