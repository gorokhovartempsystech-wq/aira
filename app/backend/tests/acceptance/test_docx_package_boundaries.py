"""Independent malformed-package, resource and inert-I/O checks for D02-01."""

import base64
import io
import json
import stat
import struct
import subprocess
import sys
import traceback
import warnings
import zipfile
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "SYNTHETIC_PRIVATE_DOCX_BOUNDARY_854"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
RELS_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
DEFAULT_LIMITS = {
    "max_archive_bytes": 33554432,
    "max_entries": 4096,
    "max_part_bytes": 67108864,
    "max_total_uncompressed_bytes": 134217728,
    "max_xml_bytes": 8388608,
}


def api():
    return import_module("ara.docx_package")


def xml(root, encoding="utf-8"):
    return ET.tostring(root, encoding=encoding, xml_declaration=True)


def content_types(*, main_type=MAIN_TYPE):
    root = ET.Element(f"{{{CT_NS}}}Types")
    for extension, content_type in (
        ("rels", RELS_TYPE),
        ("xml", "application/xml"),
        ("bin", "application/octet-stream"),
    ):
        ET.SubElement(
            root,
            f"{{{CT_NS}}}Default",
            Extension=extension,
            ContentType=content_type,
        )
    ET.SubElement(
        root,
        f"{{{CT_NS}}}Override",
        PartName="/word/document.xml",
        ContentType=main_type,
    )
    return xml(root)


def relationships(*items):
    root = ET.Element(f"{{{REL_NS}}}Relationships")
    for item in items:
        ET.SubElement(root, f"{{{REL_NS}}}Relationship", item)
    return xml(root)


def main_relationship(**overrides):
    return {"Id": "rId1", "Type": OFFICE_REL, "Target": "word/document.xml", **overrides}


def parts():
    root = ET.Element(f"{{{WORD_NS}}}document")
    body = ET.SubElement(root, f"{{{WORD_NS}}}body")
    paragraph = ET.SubElement(body, f"{{{WORD_NS}}}p")
    run = ET.SubElement(paragraph, f"{{{WORD_NS}}}r")
    ET.SubElement(run, f"{{{WORD_NS}}}t").text = PRIVATE
    return {
        "[Content_Types].xml": content_types(),
        "_rels/.rels": relationships(main_relationship()),
        "word/document.xml": xml(root),
    }


def package(items=None, *, compression=zipfile.ZIP_STORED):
    values = parts() if items is None else items
    values = values.items() if isinstance(values, dict) else values
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w", compression=compression) as archive:
            for name, data in values:
                archive.writestr(name, data)
    return output.getvalue()


def reject(operation, code, *, forbidden=()):
    with pytest.raises(api().DocxError) as caught:
        operation()
    error = caught.value
    assert error.code == code
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message
    assert error.__cause__ is None
    assert error.__context__ is None or error.__suppress_context__
    rendered = "".join(traceback.format_exception(error))
    for marker in (PRIVATE, *forbidden):
        assert marker not in error.message + repr(error)
        assert marker not in rendered
    return error.message


def reject_package(data, code="invalid_package", *, forbidden=(), **kwargs):
    return reject(lambda: api().open_docx(data, **kwargs), code, forbidden=forbidden)


def test_nonbyte_inputs_are_rejected_without_coercion():
    for value in (
        None,
        PRIVATE,
        Path(PRIVATE),
        bytearray(package()),
        memoryview(package()),
        1,
        True,
        {},
        [],
    ):
        reject_package(value, "invalid_input")


def test_foreign_limits_and_export_arguments_are_rejected():
    module = api()
    for value in ({}, DEFAULT_LIMITS, 1, True, PRIVATE, object()):
        reject(lambda: module.open_docx(package(), limits=value), "invalid_input")
    for value in (None, package(), {}, PRIVATE, object()):
        reject(lambda: module.export_original(value), "invalid_input")


@pytest.mark.parametrize("field", tuple(DEFAULT_LIMITS))
def test_limit_values_are_strict_positive_integers(field):
    module = api()
    for value in (0, -1, True, 1.0, "1", None):
        reject(
            lambda: module.open_docx(package(), limits=module.DocxLimits(**{field: value})),
            "invalid_input",
        )


def test_limits_defaults_are_exact_and_immutable():
    limits = api().DocxLimits()
    for field, expected in DEFAULT_LIMITS.items():
        assert type(getattr(limits, field)) is int
        assert getattr(limits, field) == expected
        with pytest.raises(Exception):
            setattr(limits, field, expected + 1)
        assert getattr(limits, field) == expected


@pytest.mark.parametrize("field", tuple(DEFAULT_LIMITS))
def test_resource_limits_accept_exact_boundary_and_reject_one_less(field):
    module = api()
    values = parts()
    values["opaque.bin"] = b"x" * 4096
    values["word/"] = b""
    raw = package(values, compression=zipfile.ZIP_DEFLATED)
    file_sizes = [len(value) for name, value in values.items() if not name.endswith("/")]
    exact = {
        "max_archive_bytes": len(raw),
        "max_entries": len(values),
        "max_part_bytes": max(file_sizes),
        "max_total_uncompressed_bytes": sum(file_sizes),
        "max_xml_bytes": max(
            len(value) for name, value in values.items() if name.endswith((".xml", ".rels"))
        ),
    }[field]
    source = module.open_docx(raw, limits=module.DocxLimits(**{field: exact}))
    assert module.export_original(source) == raw
    reject_package(
        raw,
        "package_limit_exceeded",
        limits=module.DocxLimits(**{field: exact - 1}),
    )


def test_archive_limit_is_checked_before_opening_zip(monkeypatch):
    module = api()
    raw = package()

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized archive was opened before its byte limit was checked")

    monkeypatch.setattr(zipfile.ZipFile, "__init__", forbidden)
    reject_package(
        raw, "package_limit_exceeded", limits=module.DocxLimits(max_archive_bytes=len(raw) - 1)
    )


@pytest.mark.parametrize("field", ["max_entries", "max_part_bytes", "max_total_uncompressed_bytes"])
def test_declared_zip_limits_precede_decompression(monkeypatch, field):
    module = api()
    values = {**parts(), "oversized.bin": b"x" * 16384}
    raw = package(values, compression=zipfile.ZIP_DEFLATED)
    boundary = {
        "max_entries": len(values) - 1,
        "max_part_bytes": 16383,
        "max_total_uncompressed_bytes": sum(map(len, values.values())) - 1,
    }[field]

    def forbidden(*args, **kwargs):
        pytest.fail("ZIP content was decompressed before declared resource limits were checked")

    monkeypatch.setattr(zipfile.ZipExtFile, "read", forbidden)
    reject_package(raw, "package_limit_exceeded", limits=module.DocxLimits(**{field: boundary}))


def test_xml_limit_rejects_before_unbounded_read_of_large_xml(monkeypatch):
    module = api()
    values = parts()
    values["large.xml"] = b"<opaque>" + b"x" * 16384 + b"</opaque>"
    raw = package(values, compression=zipfile.ZIP_DEFLATED)
    limit = 2048
    original = zipfile.ZipExtFile.read

    def guarded(stream, size=-1):
        if stream.name == "large.xml":
            assert 0 <= size <= limit + 1, "Oversized XML was read without a useful bound"
        return original(stream, size)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", guarded)
    reject_package(raw, "package_limit_exceeded", limits=module.DocxLimits(max_xml_bytes=limit))


def test_invalid_and_truncated_zip_data_is_rejected_safely():
    raw = package()
    for value in (
        b"",
        PRIVATE.encode(),
        b"PK\x03\x04" + PRIVATE.encode(),
        raw[:40],
        raw[:-40],
        package({}),
    ):
        reject_package(value)


def test_crc_of_uninterpreted_binary_part_is_checked():
    marker = (PRIVATE + " CRC payload").encode()
    raw = package({**parts(), "opaque.bin": marker})
    at = raw.index(marker)
    damaged = raw[:at] + bytes([raw[at] ^ 1]) + raw[at + 1 :]
    reject_package(damaged, forbidden=("opaque.bin",))


def test_encrypted_entries_are_explicitly_unsupported():
    raw = bytearray(package())
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    for offset in (local + 6, central + 8):
        flags = struct.unpack_from("<H", raw, offset)[0]
        struct.pack_into("<H", raw, offset, flags | 1)
    reject_package(bytes(raw), "unsupported_package")


def test_non_store_deflate_compression_is_explicitly_unsupported():
    reject_package(package(compression=zipfile.ZIP_BZIP2), "unsupported_package")


def test_symlink_entry_is_explicitly_unsupported():
    linked = zipfile.ZipInfo("linked.bin")
    linked.create_system = 3
    linked.external_attr = (stat.S_IFLNK | 0o777) << 16
    reject_package(package([*parts().items(), (linked, PRIVATE.encode())]), "unsupported_package")


def test_unsafe_or_ambiguous_zip_names_are_rejected():
    names = (
        "/private.bin",
        "../private.bin",
        "word/../private.bin",
        "word/./private.bin",
        "word//private.bin",
        "word\\private.bin",
        "word/private.bin?query",
        "word/private.bin#fragment",
        "word./private.bin",
        "word/private.bin.",
        "word/%2Fprivate.bin",
        "word/%5cprivate.bin",
        "word/%00private.bin",
        "word/%2e%2e/private.bin",
        "word/%41.bin",
        "word/%zz.bin",
        "word/%.bin",
    )
    for name in names:
        reject_package(package([*parts().items(), (name, PRIVATE.encode())]))


def test_raw_nul_zip_name_is_rejected_instead_of_truncated():
    raw = package({**parts(), "word/nulXname.bin": PRIVATE.encode()})
    # Patch both central/local names after writing because ZipInfo truncates at NUL.
    damaged = raw.replace(b"word/nulXname.bin", b"word/nul\x00name.bin")
    reject_package(damaged)


def test_duplicate_equivalent_zip_entries_are_rejected():
    for pair in (
        ("duplicate.bin", "duplicate.bin"),
        ("duplicate.bin", "DUPLICATE.BIN"),
        ("word/%e2%82%ac.bin", "word/%E2%82%AC.bin"),
    ):
        reject_package(package([*parts().items(), (pair[0], b"one"), (pair[1], b"two")]))


def test_required_package_parts_and_main_relationship_are_unambiguous():
    for missing in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
        values = parts()
        del values[missing]
        reject_package(package(values))
    for links in (
        (),
        (main_relationship(Target=PRIVATE + ".xml"),),
        (main_relationship(), main_relationship(Id="rId2")),
        (main_relationship(TargetMode="External", Target="https://example.invalid/" + PRIVATE),),
        (
            main_relationship(),
            main_relationship(
                Id="rId2", TargetMode="External", Target="https://example.invalid/" + PRIVATE
            ),
        ),
    ):
        reject_package(package({**parts(), "_rels/.rels": relationships(*links)}))


def test_non_docx_main_content_types_are_unsupported():
    for main_type in (
        "application/vnd.ms-word.document.macroEnabled.main+xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    ):
        reject_package(
            package({**parts(), "[Content_Types].xml": content_types(main_type=main_type)}),
            "unsupported_package",
        )


def test_main_xml_requires_document_and_exactly_one_direct_body():
    for markup in (
        f'<w:paragraph xmlns:w="{WORD_NS}"/>',
        f'<w:document xmlns:w="{WORD_NS}"/>',
        f'<w:document xmlns:w="{WORD_NS}"><w:p><w:body/></w:p></w:document>',
        f'<w:document xmlns:w="{WORD_NS}"><w:body/><w:body/></w:document>',
        '<document xmlns="urn:synthetic:wrong"><body/></document>',
    ):
        reject_package(package({**parts(), "word/document.xml": markup.encode()}))


def test_content_type_root_namespace_and_unique_definitions_are_validated():
    base = parts()
    for raw in (b"<Types/>", f'<Wrong xmlns="{CT_NS}"/>'.encode(), b"<Types"):
        reject_package(package({**base, "[Content_Types].xml": raw}))
    additions = (
        ("Default", {"Extension": "XML", "ContentType": "application/xml"}),
        ("Override", {"PartName": "/WORD/DOCUMENT.XML", "ContentType": MAIN_TYPE}),
        ("Override", {"PartName": "/missing.xml", "ContentType": "application/xml"}),
        ("Default", {"Extension": "missing", "ContentType": ""}),
    )
    for tag, attributes in additions:
        root = ET.fromstring(base["[Content_Types].xml"])
        ET.SubElement(root, f"{{{CT_NS}}}{tag}", attributes)
        reject_package(package({**base, "[Content_Types].xml": xml(root)}))
    reject_package(package({**base, "untyped.custom": PRIVATE.encode()}))
    root = ET.fromstring(base["[Content_Types].xml"])
    root[0].set("ContentType", "application/xml")
    reject_package(package({**base, "[Content_Types].xml": xml(root)}))


def test_relationship_parts_need_existing_source_and_correct_location():
    for name in ("word/_rels/absent.xml.rels", "word/stray.rels", "_rels/_rels/.rels.rels"):
        reject_package(package({**parts(), name: relationships()}))


def test_relationship_namespace_required_attributes_ids_and_modes_are_validated():
    for raw in (b"<Relationships/>", f'<Wrong xmlns="{REL_NS}"/>'.encode()):
        reject_package(package({**parts(), "_rels/.rels": raw}))
    duplicate = main_relationship(Type="urn:synthetic:unknown", Target="word/document.xml")
    reject_package(
        package({**parts(), "_rels/.rels": relationships(main_relationship(), duplicate)})
    )
    for field in ("Id", "Type", "Target"):
        for value in (None, ""):
            link = main_relationship()
            if value is None:
                del link[field]
            else:
                link[field] = value
            reject_package(package({**parts(), "_rels/.rels": relationships(link)}))
    for mode in ("", "internal", "SomethingElse"):
        reject_package(
            package({**parts(), "_rels/.rels": relationships(main_relationship(TargetMode=mode))})
        )


def test_internal_targets_cannot_escape_or_reference_relationship_parts():
    targets = (
        "../../private.bin",
        "../private.bin",
        "https://example.invalid/" + PRIVATE,
        "//example.invalid/private.bin",
        "word/document.xml?query",
        "word/document.xml#fragment",
        "word\\document.xml",
        "word/%2fdocument.xml",
        "word/%5Cdocument.xml",
        "word/%00document.xml",
        "%2e%2e/private.bin",
        "word/%64ocument.xml",
        "word/%zz.xml",
        "_rels/.rels",
    )
    for target in targets:
        reject_package(
            package({**parts(), "_rels/.rels": relationships(main_relationship(Target=target))})
        )
    secondary = {"Id": "rIdPrivate", "Type": "urn:synthetic:unknown", "Target": "../_rels/.rels"}
    reject_package(package({**parts(), "word/_rels/document.xml.rels": relationships(secondary)}))
    secondary["Target"] = PRIVATE + ".bin"
    reject_package(package({**parts(), "word/_rels/document.xml.rels": relationships(secondary)}))


@pytest.mark.parametrize(
    "content_type", ["application/xml", "text/xml", "application/vnd.synthetic+xml"]
)
def test_unknown_xml_parts_are_checked_for_well_formedness(content_type):
    values = parts()
    root = ET.fromstring(values["[Content_Types].xml"])
    ET.SubElement(root, f"{{{CT_NS}}}Override", PartName="/opaque.bin", ContentType=content_type)
    values["[Content_Types].xml"] = xml(root)
    values["opaque.bin"] = ("<opaque>" + PRIVATE).encode()
    reject_package(package(values))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
@pytest.mark.parametrize("part_name", ["[Content_Types].xml", "word/document.xml", "opaque.xml"])
def test_doctype_and_entities_are_rejected_in_all_xml_encodings(part_name, encoding):
    values = parts()
    markup = values.get(part_name, b"<opaque/>").decode("utf-8")
    markup = markup[markup.find("?>") + 2 :] if markup.startswith("<?xml") else markup
    for declaration in (
        "<!DOCTYPE synthetic>",
        f'<!DOCTYPE synthetic [<!ENTITY payload "{PRIVATE}">]>',
        f'<!DOCTYPE synthetic SYSTEM "https://example.invalid/{PRIVATE}">',
    ):
        raw = f'<?xml version="1.0" encoding="{encoding}"?>{declaration}{markup}'.encode(encoding)
        reject_package(package({**values, part_name: raw}))


def test_import_and_operations_are_inert_and_do_not_log_input():
    values = parts()
    values["_rels/.rels"] = relationships(
        main_relationship(),
        {
            "Id": "rIdExternal",
            "Type": "urn:synthetic:external",
            "Target": "https://example.invalid/synthetic-external-metadata",
            "TargetMode": "External",
        },
    )
    raw = package(values)
    encoded = base64.b64encode(raw).decode()
    code = """
import base64, builtins, importlib, io, json, logging, os, socket, subprocess, tempfile
from pathlib import Path
import urllib.request, zipfile
from xml.etree import ElementTree
import xml.parsers.expat
import psycopg, sqlalchemy
import ara.config, ara.db
data = base64.b64decode(PAYLOAD)
names = ['ara.docx_package'] + [
    '.'.join(p.with_suffix('').parts[1:])
    for p in sorted(Path('src/ara/docx_package').rglob('*.py')) if p.name != '__init__.py'
]
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external I/O or logging in DOCX operation')
for target, name in (
    (builtins, 'open'), (io, 'open'), (Path, 'open'), (Path, 'read_text'), (Path, 'read_bytes'),
    (Path, 'write_text'), (Path, 'write_bytes'), (Path, 'mkdir'), (os, 'open'), (os, 'mkdir'),
    (os, 'system'), (os, 'popen'), (socket, 'socket'), (socket, 'create_connection'),
    (subprocess, 'Popen'), (subprocess, 'run'), (urllib.request, 'urlopen'),
    (tempfile, 'TemporaryFile'), (tempfile, 'NamedTemporaryFile'), (tempfile, 'mkdtemp'),
    (psycopg, 'connect'), (sqlalchemy, 'create_engine'), (ara.config, 'load_settings'),
    (ara.db, 'create_database_engine'), (logging.Logger, '_log'),
):
    setattr(target, name, forbidden)
for name in names:
    importlib.import_module(name)
api = importlib.import_module('ara.docx_package')
source = api.open_docx(data)
assert api.export_original(source) == data
assert PRIVATE not in repr(source)
try:
    api.open_docx(PRIVATE.encode())
except api.DocxError as error:
    assert error.code == 'invalid_package'
    assert PRIVATE not in str(error)
else:
    raise AssertionError('Invalid DOCX unexpectedly accepted')
""".replace("PAYLOAD", json.dumps(encoded)).replace("PRIVATE", json.dumps(PRIVATE))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
