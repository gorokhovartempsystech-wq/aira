"""Count all candidate parts before interpreting any definition, including orphans."""

from xml.etree import ElementTree as ET

from ara.docx_analysis.sections._xml import parse
from ara.docx_analysis.tables._parse import word_name

from ._models import budget


class Counter:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.depth = self.characters = self.notes = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_xml_nodes)
        budget(self.depth, self.limits.max_xml_depth)
        self.characters += sum(len(value) for value in attrs.values())
        budget(self.characters, self.limits.max_xml_characters)
        if word_name(tag) in ("footnote", "endnote"):
            self.notes += 1
            budget(self.notes, self.limits.max_notes)

    def end(self, tag):
        self.depth -= 1

    def data(self, value):
        self.characters += len(value)
        budget(self.characters, self.limits.max_xml_characters)

    def start_ns(self, prefix, uri):
        self.data(uri)

    def close(self):
        return None


def preflight(data, parts, bounds, limits):
    budget(len(parts), limits.max_parts)
    counter = Counter(limits)
    for part in parts:
        parse(data, part, bounds, counter)


def build_tree(data, part, bounds):
    return parse(data, part, bounds, ET.TreeBuilder())
