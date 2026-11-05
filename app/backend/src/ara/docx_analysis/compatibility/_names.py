"""URI capabilities, XML whitespace and XML 1.0 NCNames (colon excluded)."""

import re

from ara.docx_package._xml import WORD_NAMESPACES

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
XML = "http://www.w3.org/XML/1998/namespace"
PREFIX = "{" + MC + "}"
CORE = frozenset(PREFIX + name for name in ("Ignorable", "ProcessContent", "MustUnderstand"))
UNDERSTOOD = frozenset(WORD_NAMESPACES) | {
    XML,
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",
}
# https://www.w3.org/TR/xml/#NT-NameStartChar , without colon for an NCName.
START_RANGES = (
    (0x41, 0x5A),
    (0x61, 0x7A),
    (0xC0, 0xD6),
    (0xD8, 0xF6),
    (0xF8, 0x2FF),
    (0x370, 0x37D),
    (0x37F, 0x1FFF),
    (0x200C, 0x200D),
    (0x2070, 0x218F),
    (0x2C00, 0x2FEF),
    (0x3001, 0xD7FF),
    (0xF900, 0xFDCF),
    (0xFDF0, 0xFFFD),
    (0x10000, 0xEFFFF),
)
TOKEN = re.compile(r"[^ \t\r\n]+")


def words(value):
    return (match.group() for match in TOKEN.finditer(value))


def split(name):
    if name.startswith("{"):
        return tuple(name[1:].split("}", 1))
    return "", name


def start_char(c):
    return c == "_" or any(low <= ord(c) <= high for low, high in START_RANGES)


def ncname(value):
    return (
        bool(value)
        and start_char(value[0])
        and all(
            start_char(c)
            or c in "-.0123456789\u00b7"
            or 0x300 <= ord(c) <= 0x36F
            or 0x203F <= ord(c) <= 0x2040
            for c in value[1:]
        )
    )
