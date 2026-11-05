"""Versioned note links, without fabricated display numbers or retained source trees."""

from dataclasses import dataclass, field

from ara.docx_analysis.visible_main._models import VisibleSnapshot
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-analysis/final-visible-note-stories-v1"


@dataclass(frozen=True, slots=True)
class NoteReference:
    kind: str
    reference_anchor: SourceAnchor = field(repr=False)
    paragraph_anchor: SourceAnchor = field(repr=False)
    target_anchor: SourceAnchor = field(repr=False)
    before_fragment_id: str | None
    after_fragment_id: str | None


@dataclass(frozen=True, slots=True)
class NoteSnapshot(VisibleSnapshot):
    references: tuple[NoteReference, ...] = field(repr=False)
