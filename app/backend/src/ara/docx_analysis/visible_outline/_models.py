"""An exact new profile; old list evidence and source identities stay unchanged."""

from dataclasses import dataclass, field

from ara.docx_analysis.visible_lists import ListItem
from ara.docx_analysis.visible_notes import NoteSnapshot

PROFILE = "docx-analysis/final-visible-direct-outline-v1"


@dataclass(frozen=True, slots=True)
class OutlineSnapshot(NoteSnapshot):
    lists: tuple[ListItem, ...] = field(repr=False)
