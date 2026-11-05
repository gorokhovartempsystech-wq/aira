"""Additional adversarial cases for lexical editing, using synthetic bytes only."""

from dataclasses import replace
from io import BytesIO
from struct import unpack_from
from zipfile import ZipFile, ZipInfo

import pytest

from ara.docx_package.editing import EditError, EditLimits, TextEdit, export_docx
from ara.docx_package.projection import project_docx

WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def package(xml):
    parts = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/main.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.wordprocessingml.document.main+xml"/></Types>'
        ).encode(),
        "_rels/.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="main" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="main.xml"/></Relationships>'
        ).encode(),
        "main.xml": xml,
    }
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return stream.getvalue()


def payload(data):
    with ZipFile(BytesIO(data)) as archive:
        return archive.read("main.xml")


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be"])
@pytest.mark.parametrize("leading", [" ", "\t", "\n", "\r\n"])
def test_utf16_without_bom_or_declaration_preserves_leading_xml_whitespace(codec, leading):
    old = '<w:t xml:space="preserve">old</w:t>'
    xml = (
        leading
        + f'<w:document xmlns:w="{WML}"><w:body><w:p><w:r>'
        + old
        + "</w:r></w:p></w:body></w:document>"
    ).encode(codec)
    raw = package(xml)
    span = project_docx(raw).blocks[0].spans[0]
    assert export_docx(raw, (TextEdit(span.anchor, span.text, span.text),)) == raw
    replacement = "new 😀 & text"
    result = export_docx(raw, (TextEdit(span.anchor, span.text, replacement),))
    expected_node = '<w:t xml:space="preserve">new 😀 &amp; text</w:t>'
    assert payload(result) == xml.replace(old.encode(codec), expected_node.encode(codec))
    assert project_docx(result).blocks[0].text == replacement


@pytest.mark.parametrize("codec", ["utf-8", "utf-16-le", "utf-16-be"])
def test_namespace_rebinding_unicode_names_and_lexical_attributes(codec):
    declaration = {"utf-8": "UTF-8", "utf-16-le": "UTF-16LE", "utf-16-be": "UTF-16BE"}[codec]
    old = "<字:t xmlns:字='" + WML + "' xml:space = 'pre&#115;erve' a='😀 > /&gt;'>old</字:t >"
    xml = (
        f'<?xml version="1.0" encoding="{declaration}"?>'
        f'<document xmlns="{WML}" xmlns:x="urn:unused"><body>'
        "<!-- <t>fake</t> --><?x t?><p><r>" + old + "<t>old</t></r></p></body></document>"
    ).encode(codec)
    raw = package(xml)
    span = project_docx(raw).blocks[0].spans[0]
    output = export_docx(raw, (TextEdit(span.anchor, "old", "<&😀>"),))
    new = old.replace(">old</", ">&lt;&amp;😀&gt;</")
    assert payload(output) == xml.replace(old.encode(codec), new.encode(codec))
    assert [span.text for span in project_docx(output).blocks[0].spans] == ["<&😀>", "old"]


@pytest.mark.parametrize("codec", ["utf-8", "utf-16-le", "utf-16-be"])
def test_empty_nodes_cdata_and_unedited_annotation_in_same_batch(codec):
    xml = (
        f'<w:document xmlns:w="{WML}"><w:body><w:p><w:r>'
        "<w:t /> <w:t><![CDATA[<!-- ordinary text -->]]></w:t>"
        "<w:t>un<!--keep-->changed<?keep x?></w:t></w:r></w:p></w:body></w:document>"
    ).encode(codec)
    raw = package(xml)
    spans = project_docx(raw).blocks[0].spans
    values = ("😀 &", "", "unchanged")
    edits = tuple(TextEdit(span.anchor, span.text, value) for span, value in zip(spans, values))
    output = export_docx(raw, edits)
    assert payload(output) == xml.replace(
        "<w:t />".encode(codec), '<w:t  xml:space="preserve">😀 &amp;</w:t>'.encode(codec)
    ).replace(
        "<w:t><![CDATA[<!-- ordinary text -->]]></w:t>".encode(codec),
        '<w:t xml:space="preserve"></w:t>'.encode(codec),
    )
    assert export_docx(raw, edits[::-1]) == output


@pytest.mark.parametrize("point", [0x20, 0xD7FF, 0xE000, 0xFFFD, 0x10000, 0x10FFFF])
def test_xml_character_range_inclusive_boundaries(point):
    raw = package(
        f'<document xmlns="{WML}"><body><p><r><t>x</t></r></p></body></document>'.encode()
    )
    span = project_docx(raw).blocks[0].spans[0]
    output = export_docx(raw, (TextEdit(span.anchor, "x", chr(point)),))
    assert project_docx(output).blocks[0].text == chr(point)


def test_deleted_slots_are_rejected_and_cannot_skip_validation():
    raw = package(
        f'<document xmlns="{WML}"><body><p><r><t>x</t></r></p></body></document>'.encode()
    )
    span = project_docx(raw).blocks[0].spans[0]
    for field in ("anchor", "expected_text", "replacement_text"):
        edit = TextEdit(span.anchor, "x", "y")
        object.__delattr__(edit, field)
        with pytest.raises(EditError, match="Invalid DOCX edit input"):
            export_docx(raw, (edit,))
    for field in ("path", "part_name", "source_sha256"):
        edit = TextEdit(replace(span.anchor), "x", "y")
        object.__delattr__(edit.anchor, field)
        with pytest.raises(EditError, match="Invalid DOCX edit input"):
            export_docx(raw, (edit,))
    limits = EditLimits()
    object.__delattr__(limits, "max_edits")
    with pytest.raises(EditError, match="Invalid DOCX edit input"):
        export_docx(raw, (), edit_limits=limits)


def test_local_and_central_extra_fields_are_preserved_independently():
    raw = package(
        f'<document xmlns="{WML}"><body><p><r><t>x</t></r></p></body></document>'.encode()
    )
    local_extra = b"\xfe\xca\x03\x00LOC"
    central_extra = b"\xfe\xca\x03\x00DIR"
    stream = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(stream, "w") as destination:
        for original in source.infolist():
            info = ZipInfo(original.filename, original.date_time)
            info.extra = local_extra
            destination.writestr(info, source.read(original))
            info.extra = central_extra
    raw = stream.getvalue()
    span = project_docx(raw).blocks[0].spans[0]
    result = export_docx(raw, (TextEdit(span.anchor, span.text, "changed"),))
    with ZipFile(BytesIO(result)) as archive:
        for info in archive.infolist():
            name_size, extra_size = unpack_from("<HH", result, info.header_offset + 26)
            at = info.header_offset + 30 + name_size
            assert result[at : at + extra_size] == local_extra
            assert info.extra == central_extra
