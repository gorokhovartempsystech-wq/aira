"""Synthetic XML and ZIP inputs for independent structural DOCX acceptance."""

from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

from docx_package_fixtures import (
    MAIN_CONTENT_TYPE,
    RELS_CONTENT_TYPE,
    STRICT_WORD_NS,
    WORD_NS,
    build_package,
    content_types_xml,
    minimal_parts,
    relationships_xml,
)

REL_ATTR_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STRICT_REL_ATTR_NS = "http://purl.oclc.org/ooxml/officeDocument/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MAIN_PART = "word/document.xml"


def document_xml(
    body: str,
    *,
    strict: bool = False,
    encoding: str = "utf-8",
    before_body: str = "",
    after_body: str = "",
) -> bytes:
    namespace = STRICT_WORD_NS if strict else WORD_NS
    relationships = STRICT_REL_ATTR_NS if strict else REL_ATTR_NS
    # Keep comments and PIs in the raw fixture to test element-only path indexes.
    markup = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:document xmlns:w="{namespace}" xmlns:r="{relationships}" '
        'xmlns:s="urn:synthetic:projection" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        f"{before_body}<w:body>{body}</w:body>{after_body}</w:document>"
    )
    return markup.encode(encoding)


def paragraph(text: str, *, properties: str = "") -> str:
    return f'<w:p>{properties}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def package(
    body: str,
    *,
    main_part: str = MAIN_PART,
    strict: bool = False,
    encoding: str = "utf-8",
    before_body: str = "",
    after_body: str = "",
    extra_parts: Mapping[str, bytes] | None = None,
    extra_types: Mapping[str, str] | None = None,
    links: Sequence[Mapping[str, str]] = (),
    comment: bytes = b"",
) -> tuple[bytes, bytes]:
    """Return archive and main XML, so tests resolve anchors independently."""
    main_xml = document_xml(
        body,
        strict=strict,
        encoding=encoding,
        before_body=before_body,
        after_body=after_body,
    )
    parts = minimal_parts(main_part, strict=strict, encoding=encoding)
    parts[main_part] = main_xml
    parts.update(extra_parts or {})
    if links:
        directory, _, basename = main_part.rpartition("/")
        relationship_part = f"{directory + '/' if directory else ''}_rels/{basename}.rels"
        parts[relationship_part] = relationships_xml(links, encoding=encoding)
    parts["[Content_Types].xml"] = content_types_xml(
        defaults={
            "rels": RELS_CONTENT_TYPE,
            "xml": "application/xml",
            "bin": "application/octet-stream",
        },
        overrides={
            "/" + main_part: MAIN_CONTENT_TYPE,
            **{"/" + name: content_type for name, content_type in (extra_types or {}).items()},
        },
        encoding=encoding,
    )
    return build_package(parts, comment=comment), main_xml
