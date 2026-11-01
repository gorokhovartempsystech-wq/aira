"""Supplemental synthetic OPC cases around ambiguity and bounded decompression."""

import random
import struct
import zlib
from hashlib import sha256
from importlib import import_module
from io import BytesIO, UnsupportedOperation
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
RELS_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
MARKER = "SYNTHETIC_ADVERSARIAL_PAYLOAD_7216"


def api():
    return import_module("ara.docx_package")


def relationships(*items):
    root = ET.Element(f"{{{REL_NS}}}Relationships")
    for item in items:
        ET.SubElement(root, f"{{{REL_NS}}}Relationship", item)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def link(identifier="main", target="word/document.xml", kind=OFFICE_REL, **attributes):
    return {"Id": identifier, "Target": target, "Type": kind, **attributes}


def parts():
    root = ET.Element(f"{{{CT_NS}}}Types")
    for extension, content_type in (
        ("rels", RELS_TYPE),
        ("xml", "application/xml"),
        ("bin", "application/octet-stream"),
    ):
        ET.SubElement(root, f"{{{CT_NS}}}Default", Extension=extension, ContentType=content_type)
    ET.SubElement(
        root, f"{{{CT_NS}}}Override", PartName="/word/document.xml", ContentType=MAIN_TYPE
    )
    return {
        "[Content_Types].xml": ET.tostring(root, encoding="utf-8", xml_declaration=True),
        "_rels/.rels": relationships(link()),
        "word/document.xml": (f'<w:document xmlns:w="{WORD_NS}"><w:body/></w:document>'.encode()),
    }


class UnseekableBytes(BytesIO):
    """Exercise normal ZIP data descriptors without writing a filesystem file."""

    def seekable(self):
        return False

    def seek(self, *args):
        raise UnsupportedOperation("Synthetic writer cannot seek")


def archive(values, *, compression=ZIP_STORED, streamed=False, force_zip64=False, comment=b""):
    output = UnseekableBytes() if streamed else BytesIO()
    with ZipFile(output, "w", compression=compression) as package:
        package.comment = comment
        for name, data in values.items():
            if force_zip64:
                with package.open(name, "w", force_zip64=True) as member:
                    member.write(data)
            else:
                package.writestr(name, data)
    return output.getvalue()


def assert_rejected(raw, *, code="invalid_package", **kwargs):
    with pytest.raises(api().DocxError) as caught:
        api().open_docx(raw, **kwargs)
    error = caught.value
    assert error.code == code
    assert error.message and str(error) == error.message
    assert MARKER not in str(error) + repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__


def entry_offsets(raw, name):
    """Find headers without assuming names/signatures cannot occur in payload bytes."""
    with ZipFile(BytesIO(raw)) as package:
        local = package.getinfo(name).header_offset
        central = package.start_dir
        for item in package.infolist():
            if item.filename == name:
                return local, central
            name_size, extra_size, comment_size = struct.unpack_from("<HHH", raw, central + 28)
            central += 46 + name_size + extra_size + comment_size
    raise AssertionError("Synthetic fixture entry is absent")


def zip64_archive():
    """Use small real entries with standard ZIP64 end records and classic sentinels."""
    raw = archive(parts())
    end = raw.rfind(b"PK\x05\x06")
    count = struct.unpack_from("<H", raw, end + 10)[0]
    size, start = struct.unpack_from("<II", raw, end + 12)
    extended = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, start)
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, end, 1)
    classic = bytearray(raw[end:])
    struct.pack_into("<HHII", classic, 8, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
    return raw[:end] + extended + locator + classic


def test_full_zip64_end_record_and_locator_preserve_original_bytes():
    raw = zip64_archive()
    # Also establish that the synthetic extended end records describe a valid ZIP.
    with ZipFile(BytesIO(raw)) as package:
        assert {item.filename: package.read(item) for item in package.infolist()} == parts()
    source = api().open_docx(raw)
    assert source.sha256 == sha256(raw).hexdigest()
    assert source.size_bytes == len(raw)
    assert api().export_original(source) == raw


@pytest.mark.parametrize("offsets", [(32,), (24, 32)])
def test_zip64_entry_counts_match_each_other_and_actual_directory(offsets):
    raw = bytearray(zip64_archive())
    extended = raw.rfind(b"PK\x06\x06")
    count = struct.unpack_from("<Q", raw, extended + 32)[0]
    for offset in offsets:
        struct.pack_into("<Q", raw, extended + offset, count - 1)
    assert_rejected(bytes(raw))


@pytest.mark.parametrize("offset,value", [(4, 1), (16, 2)])
def test_zip64_locator_rejects_split_archive_disks(offset, value):
    raw = bytearray(zip64_archive())
    locator = raw.rfind(b"PK\x06\x07")
    struct.pack_into("<I", raw, locator + offset, value)
    assert_rejected(bytes(raw), code="unsupported_package")


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
@pytest.mark.parametrize("compressible", [False, True])
def test_multichunk_binary_payload_is_fully_hashed_and_preserved(compression, compressible):
    size = 1024 * 1024 + 123
    payload = b"x" * size if compressible else random.Random(7216).randbytes(size)
    raw = archive({**parts(), "opaque.bin": payload}, compression=compression)
    source = api().open_docx(raw)
    item = next(item for item in source.entries if item.name == "opaque.bin")
    assert item.size_bytes == size
    assert item.sha256 == sha256(payload).hexdigest()
    assert api().export_original(source) == raw


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize("force_zip64", [False, True])
def test_ordinary_zip_writer_variants_preserve_bytes(compression, streamed, force_zip64):
    values = {**parts(), "opaque.bin": MARKER.encode() * 100}
    raw = archive(values, compression=compression, streamed=streamed, force_zip64=force_zip64)
    with ZipFile(BytesIO(raw)) as package:
        for item in package.infolist():
            assert bool(item.flag_bits & 8) is streamed
            if force_zip64:
                assert item.extract_version >= 45
    source = api().open_docx(raw)
    assert [(item.name, item.size_bytes, item.sha256) for item in source.entries] == [
        (name, len(payload), sha256(payload).hexdigest())
        for name, payload in sorted(values.items())
    ]
    assert api().export_original(source) == raw


@pytest.mark.parametrize("offset", [4, 6])
def test_split_archive_disk_numbers_are_explicitly_unsupported(offset):
    raw = bytearray(archive(parts()))
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<H", raw, end + offset, 1)
    assert_rejected(bytes(raw), code="unsupported_package")


@pytest.mark.parametrize("offsets", [(8,), (10,), (8, 10)])
def test_end_record_entry_counts_match_each_other_and_actual_directory(offsets):
    raw = bytearray(archive(parts()))
    end = raw.rfind(b"PK\x05\x06")
    count = struct.unpack_from("<H", raw, end + 10)[0]
    for offset in offsets:
        struct.pack_into("<H", raw, end + offset, count - 1)
    assert_rejected(bytes(raw))


@pytest.mark.parametrize("comment", [b"", b"synthetic archive metadata"])
def test_declared_archive_comment_cannot_be_truncated(comment):
    raw = bytearray(archive(parts(), comment=comment))
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<H", raw, end + 20, len(comment) + 1)
    assert_rejected(bytes(raw))


@pytest.mark.parametrize(
    "comment",
    [
        b"opaque metadata containing PK\x05\x06",
        b"opaque metadata PK\x05\x06" + b"x" * 30,
        b"opaque metadata PK\x05\x06" + b"\x00" * 18,
    ],
)
def test_archive_comment_can_contain_end_record_signature_bytes(comment):
    raw = archive(parts(), comment=comment)
    source = api().open_docx(raw)
    assert source.size_bytes == len(raw)
    assert source.sha256 == sha256(raw).hexdigest()
    assert api().export_original(source) == raw


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_declared_size_and_matching_prefix_crc_cannot_hide_uncompressed_bytes(compression):
    payload = MARKER.encode() * 200
    raw = bytearray(archive({**parts(), "opaque.bin": payload}, compression=compression))
    local, central = entry_offsets(raw, "opaque.bin")
    # ZipExtFile trusts file_size, silently truncating decompressed output. The CRC
    # below deliberately matches that truncated output, so a CRC-only check passes.
    for offset in (local + 22, central + 24):
        struct.pack_into("<I", raw, offset, 1)
    for offset in (local + 14, central + 16):
        struct.pack_into("<I", raw, offset, zlib.crc32(payload[:1]))
    assert_rejected(bytes(raw))


def test_truncated_deflate_terminator_is_rejected_even_if_payload_crc_matches():
    payload = MARKER.encode() * 200
    raw = bytearray(archive({**parts(), "opaque.bin": payload}, compression=ZIP_DEFLATED))
    local, central = entry_offsets(raw, "opaque.bin")
    compressed_size = struct.unpack_from("<I", raw, central + 20)[0]
    name_size, extra_size = struct.unpack_from("<HH", raw, local + 26)
    compressed_start = local + 30 + name_size + extra_size
    # The final empty DEFLATE marker byte can be absent while a permissive reader
    # still returns every payload byte and sees its expected CRC.
    compressed = bytes(raw[compressed_start : compressed_start + compressed_size - 1])
    probe = zlib.decompressobj(-15)
    assert probe.decompress(compressed) == payload
    assert not probe.eof
    struct.pack_into("<I", raw, local + 18, compressed_size - 1)
    struct.pack_into("<I", raw, central + 20, compressed_size - 1)
    del raw[compressed_start + compressed_size - 1]
    end = raw.rfind(b"PK\x05\x06")
    previous_start = struct.unpack_from("<I", raw, end + 16)[0]
    struct.pack_into("<I", raw, end + 16, previous_start - 1)
    assert_rejected(bytes(raw))


def test_local_filename_disagreement_is_rejected_without_exposing_name():
    raw = bytearray(archive({**parts(), MARKER + ".bin": b"opaque"}))
    local, _ = entry_offsets(raw, MARKER + ".bin")
    raw[local + 30] ^= 1
    assert_rejected(bytes(raw))


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
@pytest.mark.parametrize("part_name", ["_rels/.rels", "word/_rels/document.xml.rels", "opaque.xml"])
def test_actual_doctype_is_rejected_in_both_utf16_byte_orders(encoding, part_name):
    values = parts()
    markup = (
        relationships(link()).decode()
        if part_name == "_rels/.rels"
        else relationships().decode()
        if part_name.endswith(".rels")
        else "<opaque/>"
    )
    markup = markup.removeprefix("<?xml version='1.0' encoding='utf-8'?>")
    declaration = f'<!DOCTYPE opaque [<!ENTITY payload "{MARKER}">]>'
    values[part_name] = f'<?xml version="1.0" encoding="UTF-16"?>{declaration}{markup}'.encode(
        encoding
    )
    assert_rejected(archive(values))


def test_xml_comment_and_cdata_literals_are_not_mistaken_for_declarations():
    values = parts()
    values["opaque.xml"] = (
        b'<opaque><!-- <!DOCTYPE harmless [<!ENTITY example "literal">]> -->'
        b"<![CDATA[<!DOCTYPE literal> &unchanged;]]></opaque>"
    )
    raw = archive(values)
    source = api().open_docx(raw)
    assert api().export_original(source) == raw
    opaque = next(item for item in source.entries if item.name == "opaque.xml")
    assert opaque.sha256 == sha256(values["opaque.xml"]).hexdigest()


def test_invalid_xml_encoding_is_reported_without_parser_exception_or_source():
    values = parts()
    values["opaque.xml"] = f'<?xml version="1.0" encoding="{MARKER}"?><opaque/>'.encode()
    assert_rejected(archive(values))


def test_reserved_percent_escapes_remain_literal_part_names_and_resolve_by_hex_case():
    values = parts()
    name = "assets/%23%3f%25%3a.bin"
    values[name] = b"opaque reserved URI characters"
    values["word/_rels/document.xml.rels"] = relationships(
        link("asset", "../ASSETS/%23%3F%25%3A.BIN", "urn:synthetic:opaque")
    )
    raw = archive(values)
    source = api().open_docx(raw)
    assert source.relationships[-1].resolved_part == name
    assert source.relationships[-1].target == "../ASSETS/%23%3F%25%3A.BIN"
    assert api().export_original(source) == raw


def test_relationship_id_scope_is_per_source_and_ids_remain_case_sensitive():
    values = parts()
    values["word/opaque.bin"] = b"opaque"
    values["word/_rels/document.xml.rels"] = relationships(
        link("main", "opaque.bin", "urn:synthetic:opaque"),
        link("MAIN", "opaque.bin", "urn:synthetic:opaque"),
    )
    source = api().open_docx(archive(values))
    assert [(item.source_part, item.relationship_id) for item in source.relationships] == [
        ("/", "main"),
        ("word/document.xml", "MAIN"),
        ("word/document.xml", "main"),
    ]


def test_relationship_part_names_and_source_lookup_use_ascii_case_insensitivity():
    values = parts()
    values["word/opaque.bin"] = b"opaque"
    values["WORD/_RELS/DOCUMENT.XML.RELS"] = relationships(
        link("asset", "opaque.bin", "urn:synthetic:opaque")
    )
    source = api().open_docx(archive(values))
    relation = source.relationships[-1]
    assert relation.source_part == "word/document.xml"
    assert relation.resolved_part == "word/opaque.bin"


def test_opaque_part_without_extension_uses_override_and_is_preserved():
    values = parts()
    values["extensionless"] = b"<opaque binary: never parse"
    root = ET.fromstring(values["[Content_Types].xml"])
    ET.SubElement(
        root,
        f"{{{CT_NS}}}Override",
        PartName="/extensionless",
        ContentType="application/octet-stream",
    )
    values["[Content_Types].xml"] = ET.tostring(root)
    raw = archive(values)
    source = api().open_docx(raw)
    assert (
        next(item for item in source.entries if item.name == "extensionless").sha256
        == sha256(values["extensionless"]).hexdigest()
    )
    assert api().export_original(source) == raw


def test_xml_media_type_on_binary_extension_obeys_xml_limit():
    values = parts()
    values["opaque.bin"] = b"<opaque>" + b"x" * 4096 + b"</opaque>"
    root = ET.fromstring(values["[Content_Types].xml"])
    ET.SubElement(
        root,
        f"{{{CT_NS}}}Override",
        PartName="/opaque.bin",
        ContentType="application/vnd.synthetic+xml",
    )
    values["[Content_Types].xml"] = ET.tostring(root)
    raw = archive(values, compression=ZIP_DEFLATED)
    assert_rejected(
        raw,
        code="package_limit_exceeded",
        limits=api().DocxLimits(max_xml_bytes=2048),
    )


@pytest.mark.parametrize("directory", ["word/document.xml/", "WORD/DOCUMENT.XML/"])
def test_explicit_directory_cannot_alias_an_existing_file(directory):
    assert_rejected(archive({**parts(), directory: b""}))
