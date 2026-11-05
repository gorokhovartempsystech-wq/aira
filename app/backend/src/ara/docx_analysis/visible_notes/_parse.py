"""Aggregate raw budgets precede every catalog/style/reader semantic tree."""

from ara.docx_analysis.grid_tables import GridTableLimits, TableCatalogError
from ara.docx_analysis.moves import MoveCatalogError, MoveLimits
from ara.docx_analysis.moves._parse import Counter as MoveCounter
from ara.docx_analysis.notes import NoteCatalogError, NoteLimits
from ara.docx_analysis.notes._models import budget as note_budget
from ara.docx_analysis.notes._xml import Counter as NoteCounter
from ara.docx_analysis.retained_tables._parse import RevisionCounter
from ara.docx_analysis.sections import _xml
from ara.docx_analysis.sections._resolve import MIME
from ara.docx_analysis.tables._parse import word_name
from ara.docx_analysis.visible_main._models import VisibleViewError, budget
from ara.docx_analysis.visible_stories._parse import (
    SETTINGS_MIME,
    STORY_TYPES,
    STYLES_MIME,
    Counters,
    VisibleCounter,
    caps,
)

NOTE_TYPES = {MIME + "footnotes+xml", MIME + "endnotes+xml"}


class Markers:
    def __init__(self, limits):
        self.count, self.maximum = 0, limits.max_pieces

    def start(self, tag, attrs):
        if word_name(tag) in ("footnoteReference", "endnoteReference", "footnoteRef", "endnoteRef"):
            self.count += 1
            budget(self.count, self.maximum)

    def end(self, tag):
        pass

    def data(self, value):
        pass

    def start_ns(self, prefix, uri):
        pass


def preflight(data, source, bounds, limits):
    notes = {e.name for e in source.entries if e.content_type in NOTE_TYPES}
    stories = (
        notes
        | {source.main_part}
        | {e.name for e in source.entries if e.content_type in STORY_TYPES}
    )
    parts = stories | {
        e.name for e in source.entries if e.content_type in (STYLES_MIME, SETTINGS_MIME)
    }
    visible, markers = VisibleCounter(limits), Markers(limits)
    tables = RevisionCounter(GridTableLimits(**caps(limits)))
    moves = MoveCounter(MoveLimits(**caps(limits)))
    note_limits = NoteLimits(**caps(limits))
    definitions = NoteCounter(note_limits)
    try:
        note_budget(len(notes), note_limits.max_parts)
        for part in sorted(parts):
            visible.main = part in stories
            counters = (visible, tables, moves, markers) if visible.main else (visible,)
            if part in notes:
                counters += (definitions,)
            _xml.parse(data, part, bounds, Counters(counters))
    except (TableCatalogError, MoveCatalogError, NoteCatalogError):
        raise VisibleViewError("view_limit_exceeded") from None


def build_tree(data, part, bounds):
    return _xml.build_tree(data, part, bounds)
