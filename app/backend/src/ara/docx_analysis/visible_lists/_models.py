"""Generated markers are explicit provenance, never fabricated literal source slices."""

from dataclasses import dataclass, field

from ara.docx_analysis.visible_notes import NoteSnapshot
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-analysis/final-visible-direct-lists-v1"


@dataclass(frozen=True, slots=True)
class ListItem:
    paragraph_anchor: SourceAnchor = field(repr=False)
    properties_anchor: SourceAnchor = field(repr=False)
    definition_anchor: SourceAnchor = field(repr=False)
    instance_anchor: SourceAnchor = field(repr=False)
    start_override_anchor: SourceAnchor | None = field(repr=False)
    num_id: int
    level: int
    ordinal: int
    format: str
    label: str = field(repr=False)
    suffix: str
    fragment_ids: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ListSnapshot(NoteSnapshot):
    lists: tuple[ListItem, ...] = field(repr=False)
