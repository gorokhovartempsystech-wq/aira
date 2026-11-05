"""Count all main XML before allocating the semantic DOM, including unknown branches."""

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
NAMES = frozenset(
    "move" + kind + suffix for kind in ("From", "To") for suffix in ("", "RangeStart", "RangeEnd")
)


def move_name(tag):
    for prefix in PREFIXES:
        if tag.startswith(prefix):
            name = tag[len(prefix) :]
            return name if name in NAMES else None
    return None


class Counter:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.depth = self.characters = self.ranges = self.members = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_xml_nodes)
        budget(self.depth, self.limits.max_xml_depth)
        self.characters += sum(len(v) for v in attrs.values())
        budget(self.characters, self.limits.max_xml_characters)
        name = move_name(tag)
        if name is not None:
            if name.endswith("RangeStart"):
                self.ranges += 1
                budget(self.ranges, self.limits.max_ranges)
            elif name in ("moveFrom", "moveTo"):
                self.members += 1
                budget(self.members, self.limits.max_members)

    def end(self, tag):
        self.depth -= 1

    def data(self, value):
        self.characters += len(value)
        budget(self.characters, self.limits.max_xml_characters)

    def start_ns(self, prefix, uri):
        # XMLParser separates namespace declarations from the attrs mapping.
        # Their values still consume the same bounded XML character budget.
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
        data,
        source,
        bounds,
        ProjectionLimits(max_nodes=limits.max_xml_nodes, max_depth=limits.max_xml_depth),
    )
