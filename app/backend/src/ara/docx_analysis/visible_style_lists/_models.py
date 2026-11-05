"""A style numPr stays in its physical part, never inside an invented paragraph."""

from dataclasses import dataclass, field

from ara.docx_analysis.visible_lists import ListItem
from ara.docx_analysis.visible_notes import NoteSnapshot
from ara.docx_package.projection import SourceAnchor

PROFILE = "docx-analysis/final-visible-style-lists-v1"


@dataclass(frozen=True, slots=True)
class StyleListItem(ListItem):
    numbering_source: str
    style_reference_anchor: SourceAnchor | None = field(repr=False)
    style_chain: tuple[SourceAnchor, ...] = field(repr=False)
    level_style_anchor: SourceAnchor | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class StyleListSnapshot(NoteSnapshot):
    lists: tuple[StyleListItem, ...] = field(repr=False)
