"""Count original drawing occurrences before any semantic tree is allocated."""

from ara.docx_analysis.compatibility._xml import candidates
from ara.docx_analysis.sections import SectionLimits
from ara.docx_analysis.sections._xml import Counter, parse
from ara.docx_analysis.tables._parse import word_name
from ara.docx_analysis.visible_main._models import budget
from ara.docx_analysis.visible_stories._parse import caps


class Drawings(Counter):
    def __init__(self, limits):
        super().__init__(SectionLimits(**caps(limits)))
        self.drawings, self.maximum = 0, min(10000, limits.max_pieces)

    def start(self, tag, attrs):
        super().start(tag, attrs)
        if word_name(tag) == "drawing":
            self.drawings += 1
            budget(self.drawings, self.maximum)


def preflight(data, source, bounds, limits):
    counter = Drawings(limits)
    for part in candidates(source):
        parse(data, part, bounds, counter)
