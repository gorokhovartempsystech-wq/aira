"""Aggregate count-only preflight, before either semantic DOM is allocated."""

import io
import zipfile
from xml.etree import ElementTree as ET

from ara.docx_analysis.visibility._read import MIME
from ara.docx_package import DocxError, DocxLimits
from ara.docx_package._xml import WORD_NAMESPACES
from ara.docx_package._zip import chunks, parsing_end

from ._models import budget


class Counter:
    def __init__(self, limits):
        self.limits = limits
        self.nodes = self.characters = self.depth = 0
        self.paragraphs = self.runs = self.atoms = 0
        self.main = False

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        budget(self.nodes, self.limits.max_xml_nodes)
        budget(self.depth, self.limits.max_xml_depth)
        self.data_length(sum(len(v) for v in attrs.values()))
        if self.main:
            name = next(
                (tag[len(ns) + 2 :] for ns in WORD_NAMESPACES if tag.startswith("{" + ns + "}")), ""
            )
            if name == "p":
                self.paragraphs += 1
                budget(self.paragraphs, self.limits.max_paragraphs)
            if name == "r":
                self.runs += 1
                budget(self.runs, self.limits.max_runs)
            if name in ("t", "tab", "br", "cr"):
                self.atoms += 1
                budget(self.atoms, self.limits.max_pieces)

    def end(self, tag):
        self.depth -= 1

    def data_length(self, length):
        self.characters += length
        budget(self.characters, self.limits.max_xml_characters)

    def data(self, value):
        self.data_length(len(value))

    def close(self):
        return None


def preflight(data, source, limits):
    counter = Counter(limits)
    bounds = DocxLimits()
    parts = {source.main_part} | {e.name for e in source.entries if e.content_type == MIME}
    with (
        io.BytesIO(data[: parsing_end(data, bounds)]) as buffer,
        zipfile.ZipFile(buffer) as archive,
    ):
        for part in sorted(parts):
            counter.main = part == source.main_part
            parser = ET.XMLParser(target=counter)
            try:
                for block in chunks(
                    data, buffer, archive, archive.getinfo(part), bounds.max_xml_bytes
                ):
                    parser.feed(block)
                parser.close()
            except ET.ParseError:
                raise DocxError("invalid_package") from None
