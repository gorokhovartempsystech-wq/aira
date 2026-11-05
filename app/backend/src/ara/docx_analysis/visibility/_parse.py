"""Bound styles tree allocation using the validated package directory."""

import io
import zipfile
from xml.etree import ElementTree as ET

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package._xml import WORD_NAMESPACES
from ara.docx_package._zip import chunks, parsing_end

from ._models import budget


class Builder(ET.TreeBuilder):
    def __init__(self, limits):
        super().__init__()
        self.limits = limits
        self.nodes = self.depth = self.styles = 0
        self.style_tag = None

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_nodes)
        budget(self.depth, self.limits.max_depth)
        if self.depth == 1 and tag in {f"{{{n}}}styles" for n in WORD_NAMESPACES}:
            self.style_tag = tag.removesuffix("styles") + "style"
        if self.depth == 2 and tag == self.style_tag:
            self.styles += 1
            budget(self.styles, self.limits.max_styles)
        return super().start(tag, attrs)

    def end(self, tag):
        result = super().end(tag)
        self.depth -= 1
        return result


def parse(data, part, limits):
    bounds = DocxLimits()
    parser = ET.XMLParser(target=Builder(limits))
    try:
        with io.BytesIO(data[: parsing_end(data, bounds)]) as buffer, zipfile.ZipFile(buffer) as z:
            for block in chunks(data, buffer, z, z.getinfo(part), bounds.max_xml_bytes):
                parser.feed(block)
        return parser.close()
    except ET.ParseError:
        raise DocxError("invalid_package") from None
