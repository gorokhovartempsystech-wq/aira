"""Count all revisions and excluded payload before allocating any semantic main DOM."""

import io
import zipfile
from xml.etree import ElementTree as ET

from ara.docx_analysis.current_tables._parse import HistoryCounter
from ara.docx_analysis.tables._models import budget
from ara.docx_analysis.tables._parse import word_name
from ara.docx_package import DocxError
from ara.docx_package._zip import chunks, parsing_end
from ara.docx_package.projection import ProjectionLimits
from ara.docx_package.projection._parse import parse_main


class RevisionCounter(HistoryCounter):
    def __init__(self, limits):
        super().__init__(limits)
        self.revisions = 0

    def start(self, tag, attrs):
        super().start(tag, attrs)
        if word_name(tag) in {"ins", "del", "cellIns", "cellDel", "cellMerge"}:
            self.revisions += 1
            budget(self.revisions, self.limits.max_revisions)


def read_retained_main(data, source, bounds, limits):
    parser = ET.XMLParser(target=RevisionCounter(limits))
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
