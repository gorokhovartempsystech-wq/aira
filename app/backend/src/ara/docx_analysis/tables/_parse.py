"""Count every main XML branch before semantic allocation, including exclusions."""

import io
import zipfile
from xml.etree import ElementTree as ET

from ara.docx_package import DocxError
from ara.docx_package._xml import WORD_NAMESPACES
from ara.docx_package._zip import chunks, parsing_end
from ara.docx_package.projection import ProjectionLimits
from ara.docx_package.projection._parse import parse_main

from ._models import budget

PREFIXES = tuple("{" + ns + "}" for ns in WORD_NAMESPACES)


def word_name(tag):
    return next((tag[len(p) :] for p in PREFIXES if tag.startswith(p)), None)


class Counter:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.depth = self.characters = self.table_depth = 0
        self.counts = dict(tbl=0, tr=0, tc=0)
        self.caps = dict(tbl=limits.max_tables, tr=limits.max_rows, tc=limits.max_cells)

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_xml_nodes)
        budget(self.depth, self.limits.max_xml_depth)
        self.characters += sum(len(v) for v in attrs.values())
        budget(self.characters, self.limits.max_xml_characters)
        name = word_name(tag)
        if name in self.counts:
            self.counts[name] += 1
            budget(self.counts[name], self.caps[name])
        if name == "tbl":
            self.table_depth += 1
            budget(self.table_depth, self.limits.max_table_depth)

    def end(self, tag):
        self.depth -= 1
        if word_name(tag) == "tbl":
            self.table_depth -= 1

    def data(self, value):
        self.characters += len(value)
        budget(self.characters, self.limits.max_xml_characters)

    def start_ns(self, prefix, uri):
        self.data(uri)

    def close(self):
        return None


def read_main(data, source, bounds, limits):
    parser = ET.XMLParser(target=Counter(limits))
    with (
        io.BytesIO(data[: parsing_end(data, bounds)]) as buffer,
        zipfile.ZipFile(buffer) as archive,
    ):
        try:
            for block in chunks(
                data, buffer, archive, archive.getinfo(source.main_part), bounds.max_xml_bytes
            ):
                parser.feed(block)
            parser.close()
        except ET.ParseError:
            raise DocxError("invalid_package") from None
    return parse_main(
        data, source, bounds, ProjectionLimits(limits.max_xml_nodes, limits.max_xml_depth)
    )
