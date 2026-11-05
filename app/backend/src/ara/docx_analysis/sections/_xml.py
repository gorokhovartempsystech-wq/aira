"""Aggregate original main/settings budgets before any semantic tree allocation."""

import io
import zipfile
from xml.etree import ElementTree as ET

from ara.docx_analysis.tables._parse import word_name
from ara.docx_package import DocxError
from ara.docx_package._zip import chunks, parsing_end

from ._models import budget


class Counter:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.depth = self.characters = 0
        self.sections = self.references = self.histories = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_xml_nodes)
        budget(self.depth, self.limits.max_xml_depth)
        self.characters += sum(len(value) for value in attrs.values())
        budget(self.characters, self.limits.max_xml_characters)
        name = word_name(tag)
        if name == "sectPr":
            self.sections += 1
            budget(self.sections, self.limits.max_sections)
        elif name in ("headerReference", "footerReference"):
            self.references += 1
            budget(self.references, self.limits.max_references)
        elif name in ("sectPrChange", "pPrChange"):
            self.histories += 1
            budget(self.histories, self.limits.max_histories)

    def end(self, tag):
        self.depth -= 1

    def data(self, value):
        self.characters += len(value)
        budget(self.characters, self.limits.max_xml_characters)

    def start_ns(self, prefix, uri):
        self.data(uri)

    def close(self):
        return None


def parse(data, part, bounds, target):
    parser = ET.XMLParser(target=target)
    try:
        with io.BytesIO(data[: parsing_end(data, bounds)]) as buffer, zipfile.ZipFile(buffer) as z:
            for chunk in chunks(data, buffer, z, z.getinfo(part), bounds.max_xml_bytes):
                parser.feed(chunk)
        return parser.close()
    except ET.ParseError:
        raise DocxError("invalid_package") from None


def preflight(data, parts, bounds, limits):
    counter = Counter(limits)
    for part in parts:
        parse(data, part, bounds, counter)


def build_tree(data, part, bounds):
    # Only used after every selected original part passed the aggregate preflight.
    return parse(data, part, bounds, ET.TreeBuilder())
