"""Whole styles-part budget, before any semantic style tree is allocated."""

import io
import zipfile
from xml.etree import ElementTree as ET

from ara.docx_analysis.visibility._read import MIME, REL_TYPES
from ara.docx_package import DocxError
from ara.docx_package._xml import WORD_NAMESPACES
from ara.docx_package._zip import chunks, parsing_end

from ._models import budget

PREFIXES = tuple("{" + n + "}" for n in WORD_NAMESPACES)


def styles_part(source):
    candidates = {e.name for e in source.entries if e.content_type == MIME}
    links = [
        r
        for r in source.relationships
        if r.source_part == source.main_part and r.relationship_type in REL_TYPES
    ]
    if (
        len(candidates) == 1
        and len(links) == 1
        and links[0].target_mode == "Internal"
        and links[0].resolved_part in candidates
    ):
        return links[0].resolved_part
    return None


class Counter:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.depth = self.characters = self.styles = self.regions = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_xml_nodes)
        budget(self.depth, self.limits.max_xml_depth)
        self.characters += sum(len(value) for value in attrs.values())
        budget(self.characters, self.limits.max_xml_characters)
        name = next((tag[len(p) :] for p in PREFIXES if tag.startswith(p)), None)
        if name == "style":
            self.styles += 1
            budget(self.styles, self.limits.max_styles)
        elif name == "tblStylePr":
            self.regions += 1
            budget(self.regions, self.limits.max_regions)

    def end(self, tag):
        self.depth -= 1

    def data(self, text):
        self.characters += len(text)
        budget(self.characters, self.limits.max_xml_characters)

    def start_ns(self, prefix, uri):
        self.data(uri)

    def close(self):
        return None


def preflight(data, part, bounds, limits):
    if part is None:
        return
    parser = ET.XMLParser(target=Counter(limits))
    try:
        with io.BytesIO(data[: parsing_end(data, bounds)]) as buffer, zipfile.ZipFile(buffer) as z:
            for block in chunks(data, buffer, z, z.getinfo(part), bounds.max_xml_bytes):
                parser.feed(block)
        parser.close()
    except ET.ParseError:
        raise DocxError("invalid_package") from None
