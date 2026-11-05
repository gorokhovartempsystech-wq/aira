"""Count history and excluded payload before allocating any semantic main DOM."""

import io
import zipfile
from xml.etree import ElementTree as ET

from ara.docx_analysis.tables._models import budget
from ara.docx_analysis.tables._parse import Counter, word_name
from ara.docx_package import DocxError
from ara.docx_package._zip import chunks, parsing_end
from ara.docx_package.projection import ProjectionLimits
from ara.docx_package.projection._parse import parse_main

from ._context import HISTORIES


class HistoryCounter(Counter):
    def __init__(self, limits):
        super().__init__(limits)
        self.histories = 0

    def start(self, tag, attrs):
        super().start(tag, attrs)
        if word_name(tag) in HISTORIES:
            self.histories += 1
            budget(self.histories, self.limits.max_histories)


def read_current_main(data, source, bounds, limits):
    parser = ET.XMLParser(target=HistoryCounter(limits))
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
