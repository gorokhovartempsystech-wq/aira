"""Synthetic, in-memory OPC fixtures shared by independent DOCX acceptance tests."""

from collections.abc import Mapping, Sequence
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT_WORD_NS = "http://purl.oclc.org/ooxml/wordprocessingml/main"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
STRICT_OFFICE_REL = "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"
MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
RELS_CONTENT_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
PRIVATE_TEXT = "SYNTHETIC_DOCX_ORIGINAL_TEXT_4581"


def content_types_xml(
    defaults: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
    *,
    encoding: str = "utf-8",
) -> bytes:
    root = ET.Element(f"{{{CONTENT_TYPES_NS}}}Types")
    if defaults is None:
        defaults = {"rels": RELS_CONTENT_TYPE, "xml": "application/xml"}
    for extension, content_type in defaults.items():
        ET.SubElement(
            root,
            f"{{{CONTENT_TYPES_NS}}}Default",
            Extension=extension,
            ContentType=content_type,
        )
    for name, content_type in (overrides or {}).items():
        ET.SubElement(
            root,
            f"{{{CONTENT_TYPES_NS}}}Override",
            PartName=name,
            ContentType=content_type,
        )
    return ET.tostring(root, encoding=encoding, xml_declaration=True)


def relationships_xml(
    relationships: Sequence[Mapping[str, str]], *, encoding: str = "utf-8"
) -> bytes:
    root = ET.Element(f"{{{RELS_NS}}}Relationships")
    for attributes in relationships:
        ET.SubElement(root, f"{{{RELS_NS}}}Relationship", dict(attributes))
    return ET.tostring(root, encoding=encoding, xml_declaration=True)


def document_xml(*, strict: bool = False, encoding: str = "utf-8") -> bytes:
    namespace = STRICT_WORD_NS if strict else WORD_NS
    root = ET.Element(f"{{{namespace}}}document")
    body = ET.SubElement(root, f"{{{namespace}}}body")
    paragraph = ET.SubElement(body, f"{{{namespace}}}p")
    run = ET.SubElement(paragraph, f"{{{namespace}}}r")
    ET.SubElement(run, f"{{{namespace}}}t").text = PRIVATE_TEXT + " — Реле"
    return ET.tostring(root, encoding=encoding, xml_declaration=True)


def minimal_parts(
    main_part: str = "word/document.xml", *, strict: bool = False, encoding: str = "utf-8"
) -> dict[str, bytes]:
    # Deliberately not ZIP-name order: sorting is the loader's responsibility.
    return {
        main_part: document_xml(strict=strict, encoding=encoding),
        "_rels/.rels": relationships_xml(
            [
                {
                    "Id": "rMain",
                    "Type": STRICT_OFFICE_REL if strict else OFFICE_REL,
                    "Target": main_part,
                }
            ],
            encoding=encoding,
        ),
        "[Content_Types].xml": content_types_xml(
            overrides={"/" + main_part: MAIN_CONTENT_TYPE}, encoding=encoding
        ),
    }


def build_package(
    parts: Mapping[str, bytes] | Sequence[tuple[str, bytes]],
    *,
    compression: int = ZIP_DEFLATED,
    comment: bytes = b"",
    directories: Sequence[str] = (),
) -> bytes:
    """Build only synthetic bytes, retaining order and optional duplicate entries."""
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.comment = comment
        for directory in directories:
            entry = ZipInfo(directory, date_time=(2024, 2, 6, 8, 10, 12))
            entry.create_system = 3
            entry.external_attr = (0o40755 << 16) | 0x10
            archive.writestr(entry, b"")
        pairs = parts.items() if isinstance(parts, Mapping) else parts
        for index, (name, payload) in enumerate(pairs):
            entry = ZipInfo(name, date_time=(2024, 2, 6, 8, 10, 12))
            entry.compress_type = compression
            entry.create_system = 3
            entry.external_attr = 0o100640 << 16
            entry.comment = f"synthetic-part-{index}".encode("ascii")
            entry.extra = b"\xfe\xca\x02\x00OK"
            archive.writestr(entry, payload)
    return stream.getvalue()
