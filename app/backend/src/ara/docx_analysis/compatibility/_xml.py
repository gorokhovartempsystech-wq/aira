"""Aggregate raw SAX budgets before any semantic decision, including inactive parts."""

from ara.docx_analysis.sections._xml import parse

from ._models import budget
from ._names import CORE, PREFIX, words

BASE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
TYPES = frozenset(
    BASE + name + "+xml"
    for name in ("styles", "settings", "header", "footer", "footnotes", "endnotes")
)


def candidates(source):
    return tuple(
        sorted(
            {source.main_part}
            | {entry.name for entry in source.entries if entry.content_type in TYPES}
        )
    )


class Counter:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.depth = self.characters = self.mc_items = self.namespaces = 0
        self.has_mc = False

    def add_mc(self, count=1):
        self.mc_items += count
        budget(self.mc_items, self.limits.max_mc_items)

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_xml_nodes)
        budget(self.depth, self.limits.max_xml_depth)
        self.data(tag)
        if tag.startswith(PREFIX):
            self.has_mc = True
            self.add_mc()
        for name, value in attrs.items():
            self.data(name)
            self.data(value)
            if name.startswith(PREFIX):
                self.has_mc = True
                self.add_mc()
            if name in CORE or (tag == PREFIX + "Choice" and name == "Requires"):
                for _ in words(value):
                    self.add_mc()

    def end(self, tag):
        self.depth -= 1

    def data(self, value):
        self.characters += len(value)
        budget(self.characters, self.limits.max_xml_characters)

    def start_ns(self, prefix, uri):
        self.namespaces += 1
        budget(self.namespaces, self.limits.max_namespace_declarations)
        self.data(prefix or "")
        self.data(uri)

    def close(self):
        return None


def preflight(data, parts, bounds, limits):
    budget(len(parts), limits.max_parts)
    counter = Counter(limits)
    for part in parts:
        parse(data, part, bounds, counter)
    return counter.has_mc
