"""Whole-original aggregate budgets, including inactive and unreferenced stories."""

from ara.docx_analysis.grid_tables import GridTableLimits, TableCatalogError
from ara.docx_analysis.moves import MoveCatalogError, MoveLimits
from ara.docx_analysis.moves._parse import Counter as MoveCounter
from ara.docx_analysis.retained_tables._parse import RevisionCounter
from ara.docx_analysis.sections import _xml
from ara.docx_analysis.sections._resolve import MIME
from ara.docx_analysis.visibility._read import MIME as STYLES_MIME
from ara.docx_analysis.visible_main._models import VisibleViewError
from ara.docx_analysis.visible_main._parse import Counter

STORY_TYPES = {MIME + "header+xml", MIME + "footer+xml"}
SETTINGS_MIME = MIME + "settings+xml"


class VisibleCounter(Counter):
    def start_ns(self, prefix, uri):
        self.data(uri)


class Counters:
    def __init__(self, counters):
        self.counters = counters

    def start(self, tag, attrs):
        for counter in self.counters:
            counter.start(tag, attrs)

    def end(self, tag):
        for counter in self.counters:
            counter.end(tag)

    def data(self, value):
        for counter in self.counters:
            counter.data(value)

    def start_ns(self, prefix, uri):
        for counter in self.counters:
            counter.start_ns(prefix, uri)

    def close(self):
        return None


def caps(limits):
    return dict(
        max_xml_nodes=limits.max_xml_nodes,
        max_xml_depth=limits.max_xml_depth,
        max_xml_characters=limits.max_xml_characters,
    )


def preflight(data, source, bounds, limits):
    stories = {source.main_part} | {e.name for e in source.entries if e.content_type in STORY_TYPES}
    parts = stories | {
        e.name for e in source.entries if e.content_type in {STYLES_MIME, SETTINGS_MIME}
    }
    visible = VisibleCounter(limits)
    tables = RevisionCounter(GridTableLimits(**caps(limits)))
    moves = MoveCounter(MoveLimits(**caps(limits)))
    try:
        for part in sorted(parts):
            visible.main = part in stories
            counters = (visible, tables, moves) if visible.main else (visible,)
            _xml.parse(data, part, bounds, Counters(counters))
    except (TableCatalogError, MoveCatalogError):
        raise VisibleViewError("view_limit_exceeded") from None


def build_tree(data, part, bounds):
    return _xml.build_tree(data, part, bounds)
