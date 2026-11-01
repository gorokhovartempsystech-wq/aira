"""Deferred, strict wire commands; native DTO validation before opening storage."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.projection import SourceAnchor
from ara.docx_package.structure import DeleteParagraph, InsertParagraph

from ._dto import MAX_REVISION
from .text_edit_schemas import TextEditAnchor, TextEditReceipt


class ParagraphRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)


class AnchoredCommand(ParagraphRecord):
    anchor: TextEditAnchor
    expected_text: str = Field(max_length=100000, repr=False)

    def source_anchor(self):
        return SourceAnchor(
            self.anchor.source_sha256, self.anchor.part_name, tuple(self.anchor.path)
        )


class InsertCommand(AnchoredCommand):
    kind: Literal["insert"]
    texts: list[Annotated[str, Field(max_length=100000)]] = Field(
        min_length=1, max_length=1000, repr=False
    )
    position: Literal["before", "after"] = "after"

    def native(self):
        return InsertParagraph(
            self.source_anchor(), self.expected_text, tuple(self.texts), self.position
        )


class DeleteCommand(AnchoredCommand):
    kind: Literal["delete"]

    def native(self):
        return DeleteParagraph(self.source_anchor(), self.expected_text)


class FormatCommand(AnchoredCommand):
    kind: Literal["format"]
    style_id: str | None = Field(default=None, min_length=1, max_length=255)
    list_kind: Literal["none", "bullet", "numbered"] = "none"
    list_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,9}$")

    def native(self):
        return ParagraphFormat(
            self.source_anchor(), self.expected_text, self.style_id, self.list_kind, self.list_id
        )


Command = Annotated[InsertCommand | DeleteCommand | FormatCommand, Field(discriminator="kind")]


class ParagraphCommandsRequest(ParagraphRecord):
    expected_storage_revision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    kind: Literal["structure", "format"]
    commands: list[Command] = Field(min_length=1, max_length=1000, repr=False)

    @field_validator("expected_storage_revision")
    @classmethod
    def revision_bound(cls, value):
        if not 1 <= int(value) <= MAX_REVISION - 1:
            raise ValueError("Invalid revision")
        return value

    @model_validator(mode="after")
    def native_validation(self):
        paragraphs, chars = 0, 0
        for command in self.commands:
            if (command.kind == "format") != (self.kind == "format"):
                raise ValueError("Mixed command families")
            command.native()
            if command.kind == "insert":
                paragraphs += len(command.texts)
                chars += sum(map(len, command.texts))
        if paragraphs > 1000 or chars > 1000000:
            raise ValueError("Command batch exceeds a technical limit")
        return self


class ParagraphCommandReceipt(TextEditReceipt):
    operation_id: UUID
