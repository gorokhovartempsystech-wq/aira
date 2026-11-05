"""Streaming XML validation; never resolves entities or builds document trees."""

from collections.abc import Callable
from xml.parsers import expat

from ._models import DocxError

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORD_NAMESPACES = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
)
RELS_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
OFFICE_TYPES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
)


def expanded(namespace: str, local: str) -> str:
    return namespace + "}" + local


def is_xml(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in ("application/xml", "text/xml") or media_type.endswith("+xml")


class XmlValidator:
    """Validate SAX events and optionally inspect element names/attributes."""

    def __init__(self, start: Callable[[str, dict[str, str], int], None] | None = None):
        self._depth = 0
        self._start = start
        self._parser = expat.ParserCreate(namespace_separator="}")
        self._parser.StartDoctypeDeclHandler = self._forbidden
        self._parser.EntityDeclHandler = self._forbidden
        self._parser.ExternalEntityRefHandler = self._forbidden
        self._parser.StartElementHandler = self._element
        self._parser.EndElementHandler = self._end

    @staticmethod
    def _forbidden(*args):
        # The parser recognizes declarations in UTF-8/UTF-16 before expansion.
        raise DocxError("invalid_package")

    def _element(self, name: str, attributes: dict[str, str]) -> None:
        if self._start is not None:
            self._start(name, attributes, self._depth)
        self._depth += 1

    def _end(self, name: str) -> None:
        self._depth -= 1

    def feed(self, data: bytes, *, final: bool = False) -> None:
        self._parser.Parse(data, final)
