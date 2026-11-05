"""Whole-original field counts precede semantic interpretation or visibility filtering."""

from ara.docx_analysis.sections._xml import parse
from ara.docx_analysis.tables._parse import word_name
from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_notes._parse import NOTE_TYPES
from ara.docx_analysis.visible_stories._parse import SETTINGS_MIME, STORY_TYPES, STYLES_MIME


class Counter:
    def __init__(self, limits):
        self.count, self.maximum = 0, min(10000, limits.max_pieces)

    def start(self, tag, attrs):
        name = word_name(tag)
        ns = tag.rpartition("}")[0] + "}"
        if name == "fldSimple" or (name == "fldChar" and attrs.get(ns + "fldCharType") == "begin"):
            self.count += 1
            budget(self.count, self.maximum)

    def end(self, tag):
        pass

    def data(self, value):
        pass

    def start_ns(self, prefix, uri):
        pass

    def close(self):
        return None


def preflight(data, source, bounds, limits):
    types = STORY_TYPES | NOTE_TYPES | {STYLES_MIME, SETTINGS_MIME}
    parts = {source.main_part} | {e.name for e in source.entries if e.content_type in types}
    counter = Counter(limits)
    for part in sorted(parts):
        parse(data, part, bounds, counter)
