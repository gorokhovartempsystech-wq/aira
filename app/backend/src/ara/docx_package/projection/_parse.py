"""Bound tree allocation during parsing of the already validated main part."""

import io
import zipfile
from xml.etree import ElementTree as ET

from .. import DocxError, DocxLimits, DocxSource
from .._zip import chunks, parsing_end
from ._models import ProjectionError, ProjectionLimits


class _BoundedBuilder(ET.TreeBuilder):
    def __init__(self, limits: ProjectionLimits) -> None:
        super().__init__()
        self.limits = limits
        self.nodes = 0
        self.depth = 0

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        if self.nodes > self.limits.max_nodes or self.depth > self.limits.max_depth:
            # Reject before allocating the element, including hidden content.
            raise ProjectionError("projection_limit_exceeded")
        return super().start(tag, attrs)

    def end(self, tag):
        result = super().end(tag)
        self.depth -= 1
        return result


def parse_main(
    data: bytes, source: DocxSource, limits: DocxLimits, projection_limits: ProjectionLimits
) -> ET.Element:
    # open_docx has validated every part (including DTD/entity rejection). Use
    # its same ZIP boundary and chunk reader: EOCD signatures in comments are
    # legal and must not cause ZipFile to select a different directory.
    end = parsing_end(data, limits)
    parser = ET.XMLParser(target=_BoundedBuilder(projection_limits))
    with io.BytesIO(data[:end]) as buffer, zipfile.ZipFile(buffer, "r") as archive:
        info = archive.getinfo(source.main_part)
        for block in chunks(
            data, buffer, archive, info, min(limits.max_part_bytes, limits.max_xml_bytes)
        ):
            try:
                parser.feed(block)
            except ET.ParseError:
                raise DocxError("invalid_package") from None
    try:
        return parser.close()
    except ET.ParseError:
        raise DocxError("invalid_package") from None
