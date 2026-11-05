"""Bound all original controls and fields before semantic DOM, even unused branches."""

from ara.docx_analysis.sections._xml import parse
from ara.docx_analysis.tables._parse import word_name
from ara.docx_analysis.visible_fields._parse import Counter as FieldCounter
from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_notes._parse import NOTE_TYPES
from ara.docx_analysis.visible_stories._parse import (
    SETTINGS_MIME,
    STORY_TYPES,
    STYLES_MIME,
    Counters,
)


class ControlCounter:
    def __init__(self, limits):
        self.count = self.depth = 0
        self.maximum = min(10000, limits.max_pieces)
        self.depth_limit = min(32, limits.max_xml_depth)

    def start(self, tag, attrs):
        if word_name(tag) == "sdt":
            budget(self.count + 1, self.maximum)
            budget(self.depth + 1, self.depth_limit)
            self.count += 1
            self.depth += 1

    def end(self, tag):
        if word_name(tag) == "sdt":
            self.depth -= 1

    def data(self, value):
        pass

    def start_ns(self, prefix, uri):
        pass


def preflight(data, source, bounds, limits):
    types = STORY_TYPES | NOTE_TYPES | {STYLES_MIME, SETTINGS_MIME}
    parts = {source.main_part} | {e.name for e in source.entries if e.content_type in types}
    counters = Counters((FieldCounter(limits), ControlCounter(limits)))
    for part in sorted(parts):
        parse(data, part, bounds, counters)
