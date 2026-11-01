"""Independent D02-01 acceptance: untouched OPC bytes and immutable inventories."""

import importlib
import socket
import urllib.request
from hashlib import sha256
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from docx_package_fixtures import (
    MAIN_CONTENT_TYPE,
    OFFICE_REL,
    PRIVATE_TEXT,
    RELS_CONTENT_TYPE,
    STRICT_OFFICE_REL,
    STRICT_WORD_NS,
    WORD_NS,
    build_package,
    content_types_xml,
    minimal_parts,
    relationships_xml,
)


def api():
    # Absence before the Ralph implementation must fail execution, not collection.
    return importlib.import_module("ara.docx_package")


def inventory(source):
    return tuple(
        (entry.name, entry.content_type, entry.size_bytes, entry.sha256) for entry in source.entries
    )


def relations(source):
    return tuple(
        (
            relation.source_part,
            relation.relationship_id,
            relation.relationship_type,
            relation.target,
            relation.target_mode,
            relation.resolved_part,
        )
        for relation in source.relationships
    )


def assert_inventory(source, parts, expected_types):
    assert type(source.entries) is tuple
    assert inventory(source) == tuple(
        (name, expected_types[name], len(payload), sha256(payload).hexdigest())
        for name, payload in sorted(parts.items())
    )


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_original_bytes_and_zip_metadata_survive_repeated_export(compression):
    package = api()
    parts = minimal_parts()
    original = build_package(
        parts, compression=compression, comment=b"synthetic archive comment\x00\xff"
    )
    source = package.open_docx(original)
    assert isinstance(source, package.DocxSource)
    assert source.sha256 == sha256(original).hexdigest()
    assert source.size_bytes == len(original)
    assert source.main_part == "word/document.xml"
    assert_inventory(
        source,
        parts,
        {
            "[Content_Types].xml": None,
            "_rels/.rels": RELS_CONTENT_TYPE,
            "word/document.xml": MAIN_CONTENT_TYPE,
        },
    )
    for _ in range(3):
        exported = package.export_original(source)
        assert type(exported) is bytes
        assert exported == original
        reopened = package.open_docx(exported)
        assert reopened.sha256 == source.sha256
        assert inventory(reopened) == inventory(source)
        assert relations(reopened) == relations(source)
    with ZipFile(BytesIO(package.export_original(source))) as archive:
        assert archive.comment == b"synthetic archive comment\x00\xff"
        assert archive.namelist() == list(parts)
        for index, item in enumerate(archive.infolist()):
            assert item.compress_type == compression
            assert item.date_time == (2024, 2, 6, 8, 10, 12)
            assert item.comment == f"synthetic-part-{index}".encode("ascii")
            assert item.extra == b"\xfe\xca\x02\x00OK"
            assert item.external_attr == 0o100640 << 16


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_main_part_is_found_by_relationship_for_both_word_namespaces(strict, encoding):
    package = api()
    main_part = "custom/requirements.XML"
    original = build_package(minimal_parts(main_part, strict=strict, encoding=encoding))
    source = package.open_docx(original)
    assert source.main_part == main_part
    assert type(source.relationships) is tuple
    assert relations(source) == (
        (
            "/",
            "rMain",
            STRICT_OFFICE_REL if strict else OFFICE_REL,
            main_part,
            "Internal",
            main_part,
        ),
    )
    assert package.export_original(source) == original


@pytest.mark.parametrize("strict", [False, True])
def test_empty_word_body_is_valid(strict):
    package = api()
    parts = minimal_parts(strict=strict)
    namespace = STRICT_WORD_NS if strict else WORD_NS
    parts["word/document.xml"] = (
        f'<w:document xmlns:w="{namespace}"><w:body /></w:document>'.encode()
    )
    original = build_package(parts)
    assert package.export_original(package.open_docx(original)) == original


def test_directories_are_preserved_but_not_in_the_part_inventory():
    package = api()
    parts = minimal_parts()
    directories = ("word/", "_rels/", "empty/", "empty/nested/")
    original = build_package(parts, directories=directories)
    source = package.open_docx(original)
    assert tuple(item.name for item in source.entries) == tuple(sorted(parts))
    assert package.export_original(source) == original
    with ZipFile(BytesIO(package.export_original(source))) as archive:
        assert {item.filename for item in archive.infolist() if item.is_dir()} == set(directories)


def test_default_content_types_are_case_insensitive_and_override_wins():
    package = api()
    parts = minimal_parts("Word/Main.XML")
    parts["opaque/unknown.BIN"] = b"\x00\xffsynthetic opaque data"
    parts["opaque/other.bin"] = b"<not-an-xml-document"
    parts["custom/model.XML"] = b'<model xmlns="urn:synthetic:model">untouched</model>'
    parts["[Content_Types].xml"] = content_types_xml(
        defaults={"RELS": RELS_CONTENT_TYPE, "XML": "text/xml", "bIn": "application/octet-stream"},
        overrides={
            "/word/main.xml": MAIN_CONTENT_TYPE,
            "/OPAQUE/UNKNOWN.bin": "application/x-synthetic-opaque",
        },
    )
    original = build_package(parts)
    source = package.open_docx(original)
    assert_inventory(
        source,
        parts,
        {
            "[Content_Types].xml": None,
            "_rels/.rels": RELS_CONTENT_TYPE,
            "Word/Main.XML": MAIN_CONTENT_TYPE,
            "opaque/unknown.BIN": "application/x-synthetic-opaque",
            "opaque/other.bin": "application/octet-stream",
            "custom/model.XML": "text/xml",
        },
    )
    assert package.export_original(source) == original


def test_internal_relationships_resolve_paths_case_and_percent_escapes():
    package = api()
    parts = minimal_parts("Pkg/Main.XML")
    media_part = "assets/%d1%80%D0%B5%D0%BB%D0%B5%20icon.BIN"
    parts[media_part] = bytes(range(256))
    parts["root.BIN"] = b"root opaque payload"
    parts["Pkg/_rels/Main.XML.rels"] = relationships_xml(
        [
            {"Id": "zRoot", "Type": "urn:synthetic:root", "Target": "/ROOT.bin"},
            {
                "Id": "aRelative",
                "Type": "urn:synthetic:media",
                "Target": "./../ASSETS/%D1%80%d0%b5%d0%bb%d0%b5%20ICON.bin",
                "TargetMode": "Internal",
            },
        ]
    )
    parts["_rels/.rels"] = relationships_xml(
        [{"Id": "rMain", "Type": OFFICE_REL, "Target": "pkg/main.xml"}]
    )
    parts["[Content_Types].xml"] = content_types_xml(
        defaults={
            "rels": RELS_CONTENT_TYPE,
            "xml": "application/xml",
            "bin": "application/octet-stream",
        },
        overrides={"/PKG/MAIN.xml": MAIN_CONTENT_TYPE},
    )
    original = build_package(parts)
    source = package.open_docx(original)
    assert source.main_part == "Pkg/Main.XML"
    assert relations(source) == (
        ("/", "rMain", OFFICE_REL, "pkg/main.xml", "Internal", "Pkg/Main.XML"),
        (
            "Pkg/Main.XML",
            "aRelative",
            "urn:synthetic:media",
            "./../ASSETS/%D1%80%d0%b5%d0%bb%d0%b5%20ICON.bin",
            "Internal",
            media_part,
        ),
        ("Pkg/Main.XML", "zRoot", "urn:synthetic:root", "/ROOT.bin", "Internal", "root.BIN"),
    )
    assert package.export_original(source) == original


def test_external_relationship_targets_are_retained_without_network_or_validation(monkeypatch):
    package = api()
    parts = minimal_parts()
    targets = (
        "https://example.invalid/document?q=one&x=two#anchor",
        "file:///synthetic/never-open.txt",
        "not even a URI: <opaque external value>",
    )
    parts["word/_rels/document.xml.rels"] = relationships_xml(
        [
            {
                "Id": f"r{index}",
                "Type": "urn:synthetic:unknown-external",
                "Target": target,
                "TargetMode": "External",
            }
            for index, target in reversed(list(enumerate(targets)))
        ]
    )
    original = build_package(parts)

    def forbidden(*args, **kwargs):
        pytest.fail("An External relationship attempted network or URL access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    source = package.open_docx(original)
    assert relations(source)[1:] == tuple(
        (
            "word/document.xml",
            f"r{index}",
            "urn:synthetic:unknown-external",
            target,
            "External",
            None,
        )
        for index, target in enumerate(targets)
    )
    assert package.export_original(source) == original


def test_source_inventory_and_relationships_are_immutable_and_hide_original_bytes():
    package = api()
    original = build_package(minimal_parts(), compression=ZIP_STORED)
    source = package.open_docx(original)
    entry = source.entries[0]
    relation = source.relationships[0]
    before = (source.sha256, inventory(source), relations(source))
    for value, field, replacement in (
        (source, "sha256", "0" * 64),
        (source, "main_part", "changed.xml"),
        (source, "size_bytes", 0),
        (source, "entries", ()),
        (source, "relationships", ()),
        (entry, "name", "changed.xml"),
        (entry, "sha256", "0" * 64),
        (relation, "target", "changed.xml"),
        (relation, "resolved_part", None),
    ):
        with pytest.raises((AttributeError, TypeError)):
            setattr(value, field, replacement)
    assert type(source.entries) is tuple
    assert type(source.relationships) is tuple
    assert PRIVATE_TEXT not in repr(source)
    assert (source.sha256, inventory(source), relations(source)) == before
    assert package.export_original(source) == original


def test_rich_and_unknown_parts_are_retained_without_rewriting_xml():
    package = api()
    parts = minimal_parts()
    # This synthetic package exercises retention, not full Word schema/rendering validation.
    parts["word/document.xml"] = f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{WORD_NS}" xmlns:s="urn:synthetic:extension">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Требования</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>
      <w:r><w:t>Список</w:t></w:r></w:p>
    <w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>
      <w:p><w:r><w:t>Объединённая ячейка</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    <w:p><w:ins w:id="1"><w:r><w:t>Правка</w:t></w:r></w:ins>
      <w:del w:id="2"><w:r><w:delText>Удаление</w:delText></w:r></w:del>
      <w:commentRangeStart w:id="3"/><w:r><w:t>Текст</w:t></w:r>
      <w:commentRangeEnd w:id="3"/><w:r><w:commentReference w:id="3"/></w:r>
      <w:r><w:drawing><s:opaqueDraw/></w:drawing></w:r></w:p>
    <s:futureElement s:flag="preserve"><!-- retain lexical whitespace --></s:futureElement>
    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr>
  </w:body>
</w:document>'''.encode()
    word_parts = {
        "styles": "styles",
        "numbering": "numbering",
        "header1": "hdr",
        "footer1": "ftr",
        "comments": "comments",
        "footnotes": "footnotes",
        "endnotes": "endnotes",
    }
    content_types = {"/word/document.xml": MAIN_CONTENT_TYPE}
    word_prefix = "application/vnd.openxmlformats-officedocument.wordprocessingml."
    for name, root in word_parts.items():
        part = f"word/{name}.xml"
        parts[part] = f'<w:{root} xmlns:w="{WORD_NS}"><!-- synthetic --></w:{root}>'.encode()
        suffix = "header" if name == "header1" else "footer" if name == "footer1" else name
        content_types["/" + part] = word_prefix + suffix + "+xml"
    parts["customXml/future.xml"] = (
        b'<?xml version="1.0"?><future xmlns="urn:synthetic:unknown">\n'
        b'  <!-- spelling and whitespace retained --> <item value="A&#38;B"/>\n</future>'
    )
    content_types["/customXml/future.xml"] = "application/x-synthetic-future+xml"
    parts["word/media/synthetic.bin"] = b"\x89synthetic image bytes\x00\xff"
    parts["word/embeddings/opaque.bin"] = b"opaque object: never execute or inspect\x00"
    parts["word/_rels/document.xml.rels"] = relationships_xml(
        [
            {"Id": f"r{index:02}", "Type": "urn:synthetic:" + name, "Target": name + ".xml"}
            for index, name in enumerate(reversed(word_parts))
        ]
        + [
            {"Id": "rMedia", "Type": "urn:synthetic:image", "Target": "media/synthetic.bin"},
            {"Id": "rObject", "Type": "urn:synthetic:object", "Target": "embeddings/opaque.bin"},
            {"Id": "rUnknown", "Type": "urn:synthetic:future", "Target": "../customXml/future.xml"},
        ]
    )
    parts["[Content_Types].xml"] = content_types_xml(
        defaults={
            "rels": RELS_CONTENT_TYPE,
            "xml": "application/xml",
            "bin": "application/octet-stream",
        },
        overrides=content_types,
    )
    original = build_package(parts, comment=b"synthetic rich document")
    source = package.open_docx(original)
    expected_types = {
        name: content_types.get(
            "/" + name,
            RELS_CONTENT_TYPE if name.endswith(".rels") else "application/octet-stream",
        )
        for name in parts
    }
    expected_types["[Content_Types].xml"] = None
    assert_inventory(source, parts, expected_types)
    assert len(source.relationships) == 1 + len(word_parts) + 3
    assert package.export_original(source) == original
    with ZipFile(BytesIO(package.export_original(source))) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == parts
    # Guard the fixture itself against accidental text-only replacement.
    root = ET.fromstring(parts["word/document.xml"])
    assert root.find(f".//{{{WORD_NS}}}tbl") is not None
    assert root.find(f".//{{{WORD_NS}}}ins") is not None
