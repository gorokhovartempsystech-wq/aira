"""Deferred wire schemas for structural DOCX viewing, never Word rendering."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ViewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, defer_build=True)


class ViewAnchor(ViewRecord):
    source_sha256: str
    part_name: str
    path: list[int]


class ViewHyperlink(ViewRecord):
    anchor: ViewAnchor
    relationship_id: str | None
    bookmark: str | None


class ViewSpan(ViewRecord):
    kind: str
    anchor: ViewAnchor
    run_anchor: ViewAnchor | None
    text: str
    start: int
    end: int
    xml_space: str | None
    break_type: str | None
    hyperlink: ViewHyperlink | None
    reason: str | None


class ViewParagraph(ViewRecord):
    kind: Literal["paragraph"]
    anchor: ViewAnchor
    text: str
    spans: list[ViewSpan]
    properties_anchor: ViewAnchor | None
    style_id: str | None
    numbering_id: str | None
    numbering_level: str | None
    has_opaque: bool


class ViewOpaque(ViewRecord):
    kind: Literal["opaque"]
    anchor: ViewAnchor
    reason: str
    element_name: str


class ViewCell(ViewRecord):
    anchor: ViewAnchor
    blocks: list[ViewBlock]
    properties_anchor: ViewAnchor | None
    grid_span: str | None
    vertical_merge: str | None


class ViewRow(ViewRecord):
    anchor: ViewAnchor
    cells: list[ViewCell]
    properties_anchor: ViewAnchor | None


class ViewTable(ViewRecord):
    kind: Literal["table"]
    anchor: ViewAnchor
    rows: list[ViewRow]
    properties_anchor: ViewAnchor | None


ViewBlock = Annotated[ViewParagraph | ViewTable | ViewOpaque, Field(discriminator="kind")]


class ViewNotice(ViewRecord):
    code: str
    part_name: str
    anchor: ViewAnchor | None


class DocxView(ViewRecord):
    document_id: UUID
    title: str
    storage_revision: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    current_sha256: str
    current_size_bytes: int
    created_at: datetime
    updated_at: datetime
    body_anchor: ViewAnchor
    coverage_scope: Literal["main-body-structural-v1"]
    has_unprojected_content: bool
    blocks: list[ViewBlock]
    notices: list[ViewNotice]
