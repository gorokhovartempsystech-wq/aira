"""Independent positive D02-03 acceptance, fixed before implementation."""

import codecs
import copy
from dataclasses import FrozenInstanceError
from hashlib import sha256
from importlib import import_module
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from docx_editing_fixtures import MAIN, edit_api, projection_api, raw_package, text_spans, zip_parts
from docx_package_fixtures import STRICT_WORD_NS, WORD_NS, build_package
from docx_projection_fixtures import REL_ATTR_NS, XML_NS, document_xml, package, paragraph

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"


def edit(span, replacement):
    return edit_api().TextEdit(span.anchor, span.text, replacement)


def assert_preserved_parts(original, exported, *, main=MAIN, comment=b""):
    before = zip_parts(original, comment=comment)
    after = zip_parts(exported, comment=comment)
    assert list(after) == list(before)
    assert {name: data for name, data in after.items() if name != main} == {
        name: data for name, data in before.items() if name != main
    }
    source = import_module("ara.docx_package").open_docx(exported)
    assert source.sha256 == sha256(exported).hexdigest()
    assert source.main_part == main
    return before[main], after[main]


def assert_only_node_replaced(original, exported, original_node, *, codec="utf-8"):
    # Deliberately assert exact bytes outside the one known fixture node rather
    # than serializing an XML tree or trusting the production source anchors.
    before, separator, after = original.partition(original_node)
    assert separator and original.count(original_node) == 1
    assert exported.startswith(before)
    assert exported.endswith(after)
    new_node = exported[len(before) : len(exported) - len(after) if after else None]
    wrapper = (
        f'<scope xmlns:w="{WORD_NS}" xmlns:q="{STRICT_WORD_NS}" '
        'xmlns:s="urn:synthetic:projection">' + new_node.decode(codec) + "</scope>"
    )
    return ET.fromstring(wrapper)[0]


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize(
    ("encoding", "bom", "declared"),
    [
        ("utf-8", b"", "utf-8"),
        ("utf-8", codecs.BOM_UTF8, "UTF-8"),
        ("utf-16-le", codecs.BOM_UTF16_LE, "UTF-16"),
        ("utf-16-be", codecs.BOM_UTF16_BE, "UTF-16"),
        ("utf-16-le", b"", "UTF-16LE"),
        ("utf-16-be", b"", "UTF-16BE"),
    ],
)
def test_edit_preserves_namespaces_encoding_bom_and_all_other_xml(strict, encoding, bom, declared):
    namespace = STRICT_WORD_NS if strict else WORD_NS
    prefix = "q" if strict else "w"
    old_node = f'<{prefix}:t s:note="a > b &quot;quoted&quot;">Old &amp; text</{prefix}:t>'
    markup = (
        f'<?xml version="1.0" encoding="{declared}" standalone="yes"?>\r\n'
        f'<{prefix}:document xmlns:{prefix}="{namespace}" '
        'xmlns:s="urn:synthetic:projection" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        f'mc:Ignorable="s"><!-- retain --><?keep value?><{prefix}:body>'
        f"<{prefix}:p><{prefix}:r><{prefix}:rPr><{prefix}:b/></{prefix}:rPr>"
        f'{old_node}</{prefix}:r></{prefix}:p><s:unknown s:val="untouched"/>'
        f"</{prefix}:body></{prefix}:document>"
    )
    main_xml = bom + markup.encode(encoding)
    main = "custom/Document.XML"
    raw = raw_package(main_xml, main_part=main)
    span = text_spans(projection_api().project_docx(raw))[0]
    new_text = "  Реле & <sensor> \"quoted\" 'apostrophe' 😀 e\u0301  "
    exported = edit_api().export_docx(raw, (edit(span, new_text),))
    assert type(exported) is bytes and exported != raw
    original_xml, changed_xml = assert_preserved_parts(raw, exported, main=main)
    node = assert_only_node_replaced(
        original_xml, changed_xml, old_node.encode(encoding), codec=encoding
    )
    assert node.tag == f"{{{namespace}}}t"
    assert node.text == new_text
    assert node.attrib == {
        "{urn:synthetic:projection}note": 'a > b "quoted"',
        f"{{{XML_NS}}}space": "preserve",
    }
    changed = projection_api().project_docx(exported)
    assert text_spans(changed)[0].text == new_text
    assert text_spans(changed)[0].anchor.source_sha256 == sha256(exported).hexdigest()
    assert changed.source.sha256 != span.anchor.source_sha256


def test_empty_and_all_equal_edit_batches_are_exact_original_bytes():
    raw, _ = package(paragraph("same") + paragraph("a\nb\tc"), comment=b"original comment")
    spans = text_spans(projection_api().project_docx(raw))
    assert edit_api().export_docx(raw, ()) == raw
    assert edit_api().export_docx(raw, tuple(edit(span, span.text) for span in spans)) == raw


def test_multiple_edits_keep_run_styles_duplicate_text_and_are_order_independent():
    first = '<w:t xml:space="preserve">same</w:t>'
    second = '<w:t xml:space="preserve">second</w:t>'
    body = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/><w:numPr><w:numId w:val="7"/>'
        '<w:ilvl w:val="2"/></w:numPr></w:pPr><w:r><w:rPr><w:b/><w:i/><w:color '
        f'w:val="123456"/></w:rPr>{first}{second}</w:r></w:p>' + paragraph("same")
    )
    raw, main_xml = package(body)
    spans = text_spans(projection_api().project_docx(raw))
    changes = (edit(spans[0], "FIRST"), edit(spans[1], "SECOND"))
    exported = edit_api().export_docx(raw, changes)
    assert exported == edit_api().export_docx(raw, tuple(reversed(changes)))
    _, changed_xml = assert_preserved_parts(raw, exported)
    expected = main_xml.replace(first.encode(), first.replace("same", "FIRST").encode(), 1)
    expected = expected.replace(second.encode(), second.replace("second", "SECOND").encode(), 1)
    assert changed_xml == expected
    projected = projection_api().project_docx(exported)
    assert [span.text for span in text_spans(projected)] == ["FIRST", "SECOND", "same"]
    assert projected.blocks[0].style_id == "Heading1"
    assert projected.blocks[0].numbering_id == "7"
    assert projected.blocks[0].numbering_level == "2"


def test_hyperlink_and_nested_table_text_edits_preserve_link_and_merged_cell_properties():
    links = [
        {
            "Id": "rLink",
            "Type": REL_ATTR_NS + "/hyperlink",
            "Target": "https://example.invalid/never-fetch",
            "TargetMode": "External",
        }
    ]
    body = (
        '<w:p><w:hyperlink r:id="rLink" w:anchor="bookmark"><w:r><w:rPr><w:u '
        'w:val="single"/></w:rPr><w:t xml:space="preserve">Link</w:t></w:r>'
        '</w:hyperlink></w:p><w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
        '</w:tblPr><w:tblGrid><w:gridCol w:w="6000"/></w:tblGrid><w:tr><w:trPr/>'
        '<w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/></w:tcPr>'
        + paragraph("Outer")
        + "<w:tbl><w:tr><w:tc>"
        + paragraph("Inner")
        + "</w:tc></w:tr></w:tbl><w:p/></w:tc></w:tr></w:tbl>"
    )
    raw, main_xml = package(body, links=links)
    projected = projection_api().project_docx(raw)
    spans = text_spans(projected)
    assert [span.text for span in spans] == ["Link", "Outer", "Inner"]
    exported = edit_api().export_docx(raw, (edit(spans[0], "New link"), edit(spans[2], "New cell")))
    _, changed_xml = assert_preserved_parts(raw, exported)
    assert changed_xml == main_xml.replace(b">Link</w:t>", b">New link</w:t>").replace(
        b">Inner</w:t>", b">New cell</w:t>"
    )
    changed = projection_api().project_docx(exported)
    assert text_spans(changed)[0].hyperlink.relationship_id == "rLink"
    assert text_spans(changed)[0].hyperlink.bookmark == "bookmark"
    cell = changed.blocks[1].rows[0].cells[0]
    assert (cell.grid_span, cell.vertical_merge) == ("2", "restart")
    assert cell.blocks[1].kind == "table"


@pytest.mark.parametrize("old_node", ["<w:t/>", '<w:t s:keep="yes" />'])
def test_empty_self_closing_text_node_can_receive_text(old_node):
    raw, xml = package(f"<w:p><w:r>{old_node}</w:r></w:p>")
    span = text_spans(projection_api().project_docx(raw))[0]
    assert span.text == ""
    exported = edit_api().export_docx(raw, (edit(span, "new text"),))
    _, changed_xml = assert_preserved_parts(raw, exported)
    node = assert_only_node_replaced(xml, changed_xml, old_node.encode())
    assert node.text == "new text"
    assert node.get(f"{{{XML_NS}}}space") == "preserve"
    assert node.get("{urn:synthetic:projection}keep") == ("yes" if "keep" in old_node else None)


def test_deleting_text_keeps_empty_text_node_run_and_formatting():
    node = '<w:t xml:space="preserve">delete me</w:t>'
    raw, xml = package(f"<w:p><w:r><w:rPr><w:b/></w:rPr>{node}</w:r></w:p>")
    span = text_spans(projection_api().project_docx(raw))[0]
    exported = edit_api().export_docx(raw, (edit(span, ""),))
    _, changed_xml = assert_preserved_parts(raw, exported)
    changed_node = assert_only_node_replaced(xml, changed_xml, node.encode())
    assert changed_node.tag == f"{{{WORD_NS}}}t"
    assert (changed_node.text or "") == ""
    changed = projection_api().project_docx(exported)
    assert len(changed.blocks[0].spans) == 1
    assert changed.blocks[0].spans[0].text == ""
    assert changed.blocks[0].spans[0].run_anchor.path == span.run_anchor.path


@pytest.mark.parametrize(
    ("old_node", "old_text"),
    [
        ("<w:t><![CDATA[old <raw> & value]]></w:t>", "old <raw> & value"),
        ("<w:t>e&#x301; &amp; &#128512;</w:t>", "e\u0301 & 😀"),
    ],
)
def test_cdata_and_character_references_are_replaced_without_touching_surroundings(
    old_node, old_text
):
    raw, xml = package(f"<w:p><w:r>{old_node}</w:r></w:p>")
    span = text_spans(projection_api().project_docx(raw))[0]
    assert span.text == old_text
    value = 'new ]]> <tag>& "text"'
    exported = edit_api().export_docx(raw, (edit(span, value),))
    _, changed_xml = assert_preserved_parts(raw, exported)
    node = assert_only_node_replaced(xml, changed_xml, old_node.encode())
    assert node.text == value


@pytest.mark.parametrize("space", ["", " xml:space='default'", " xml:space='preserve'"])
def test_changed_text_preserves_whitespace_and_unrelated_attributes(space):
    old_node = f"<w:t s:a=\"literal > mark\" s:b='&quot;'{space}>Old</w:t>"
    raw, xml = package(f"<w:p><w:r>{old_node}</w:r></w:p>")
    span = text_spans(projection_api().project_docx(raw))[0]
    exported = edit_api().export_docx(raw, (edit(span, "  spaced  "),))
    _, changed_xml = assert_preserved_parts(raw, exported)
    node = assert_only_node_replaced(xml, changed_xml, old_node.encode())
    assert node.text == "  spaced  "
    assert node.attrib == {
        "{urn:synthetic:projection}a": "literal > mark",
        "{urn:synthetic:projection}b": '"',
        f"{{{XML_NS}}}space": "preserve",
    }


def test_opaque_neighbors_and_other_story_parts_are_untouched():
    target = '<w:t xml:space="preserve">visible</w:t>'
    body = (
        "<w:p><!-- before run --><?keep x?><w:r><w:rPr/><w:drawing><s:shape/>"
        f"</w:drawing>{target}<w:tab/><w:br/></w:r><!-- after --></w:p>"
        '<w:p><w:ins w:id="7"><w:r><w:t>revision</w:t></w:r></w:ins></w:p>'
        "<s:unknown><w:p><w:r><w:t>hidden</w:t></w:r></w:p></s:unknown>"
    )
    raw, xml = package(
        body,
        extra_parts={
            "word/header1.xml": b"<header>leave intact</header>",
            "custom/item.bin": b"\x00\xff",
        },
        extra_types={
            "word/header1.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
            )
        },
    )
    projected = projection_api().project_docx(raw)
    assert projected.has_unprojected_content
    span = text_spans(projected)[0]
    exported = edit_api().export_docx(raw, (edit(span, "changed"),))
    _, changed_xml = assert_preserved_parts(raw, exported)
    assert changed_xml == xml.replace(
        target.encode(), target.replace("visible", "changed").encode()
    )
    changed = projection_api().project_docx(exported)
    assert [(notice.code, notice.part_name) for notice in changed.notices] == [
        (notice.code, notice.part_name) for notice in projected.notices
    ]


def test_zip_entry_metadata_directories_compression_and_signature_like_comment_survive():
    xml = document_xml(paragraph("original"))
    parts = zip_parts(raw_package(xml, extra_parts={"custom/payload.bin": b"opaque"}))
    initial = build_package(parts, directories=("word/", "custom/"))
    comment = b"comment with fake signature PK\x05\x06 and final bytes"
    stream = BytesIO()
    with ZipFile(BytesIO(initial)) as source, ZipFile(stream, "w") as archive:
        archive.comment = comment
        for index, item in enumerate(source.infolist()):
            info = copy.copy(item)
            info.compress_type = ZIP_STORED if index % 2 else ZIP_DEFLATED
            info.internal_attr = index % 2
            info.create_system = 0 if index % 2 else 3
            archive.writestr(info, source.read(item))
    raw_bytes = bytearray(stream.getvalue())
    # writestr substitutes default permissions for zero. Patch the legitimate
    # central-directory field afterward, so exact zero preservation is tested.
    central_at = raw_bytes.index(b"PK\x01\x02")
    while raw_bytes[central_at : central_at + 4] == b"PK\x01\x02":
        name_size = int.from_bytes(raw_bytes[central_at + 28 : central_at + 30], "little")
        extra_size = int.from_bytes(raw_bytes[central_at + 30 : central_at + 32], "little")
        comment_size = int.from_bytes(raw_bytes[central_at + 32 : central_at + 34], "little")
        name = raw_bytes[central_at + 46 : central_at + 46 + name_size]
        if name == MAIN.encode():
            raw_bytes[central_at + 38 : central_at + 42] = b"\x00" * 4
        central_at += 46 + name_size + extra_size + comment_size
    raw = bytes(raw_bytes)
    with ZipFile(BytesIO(raw[: -len(comment)])) as source:
        assert source.getinfo(MAIN).external_attr == 0
    span = text_spans(projection_api().project_docx(raw))[0]
    exported = edit_api().export_docx(raw, (edit(span, "replacement"),))
    assert_preserved_parts(raw, exported, comment=comment)
    assert exported.endswith(comment)
    assert int.from_bytes(exported[-len(comment) - 2 : -len(comment)], "little") == len(comment)
    attributes = (
        "filename",
        "date_time",
        "compress_type",
        "comment",
        "create_system",
        "external_attr",
        "internal_attr",
        "extra",
    )
    with (
        ZipFile(BytesIO(raw[: -len(comment)])) as before,
        ZipFile(BytesIO(exported[: -len(comment)])) as after,
    ):
        assert [tuple(getattr(item, name) for name in attributes) for item in after.infolist()] == [
            tuple(getattr(item, name) for name in attributes) for item in before.infolist()
        ]


def extra_fields(payload):
    result = []
    at = 0
    while at < len(payload):
        tag = int.from_bytes(payload[at : at + 2], "little")
        size = int.from_bytes(payload[at + 2 : at + 4], "little")
        assert at + 4 + size <= len(payload)
        result.append((tag, payload[at + 4 : at + 4 + size]))
        at += 4 + size
    assert at == len(payload)
    return result


def test_central_zip64_extra_sizes_are_removed_or_recomputed_for_changed_main():
    xml = document_xml(paragraph("short"))
    initial = raw_package(xml, extra_parts={"custom/preserved.bin": b"unchanged"})
    with ZipFile(BytesIO(initial)) as archive:
        info = archive.getinfo(MAIN)
        old_size, old_compressed = info.file_size, info.compress_size
    raw_bytes = bytearray(initial)
    central_at = raw_bytes.index(b"PK\x01\x02")
    name_size = int.from_bytes(raw_bytes[central_at + 28 : central_at + 30], "little")
    extra_size = int.from_bytes(raw_bytes[central_at + 30 : central_at + 32], "little")
    assert raw_bytes[central_at + 46 : central_at + 46 + name_size] == MAIN.encode()
    structural_extra = (
        b"\x01\x00\x10\x00" + old_size.to_bytes(8, "little") + old_compressed.to_bytes(8, "little")
    )
    extra_at = central_at + 46 + name_size
    raw_bytes[extra_at:extra_at] = structural_extra
    raw_bytes[central_at + 20 : central_at + 28] = b"\xff" * 8
    raw_bytes[central_at + 30 : central_at + 32] = (extra_size + len(structural_extra)).to_bytes(
        2, "little"
    )
    end_at = len(raw_bytes) - 22
    assert raw_bytes[end_at : end_at + 4] == b"PK\x05\x06"
    directory_size = int.from_bytes(raw_bytes[end_at + 12 : end_at + 16], "little")
    raw_bytes[end_at + 12 : end_at + 16] = (directory_size + len(structural_extra)).to_bytes(
        4, "little"
    )
    raw = bytes(raw_bytes)
    with ZipFile(BytesIO(raw)) as archive:
        original_info = archive.getinfo(MAIN)
        assert (original_info.file_size, original_info.compress_size) == (old_size, old_compressed)
        assert extra_fields(original_info.extra)[0] == (1, structural_extra[4:])
    span = text_spans(projection_api().project_docx(raw))[0]
    value = "much longer replacement " * 23
    exported = edit_api().export_docx(raw, (edit(span, value),))
    assert_preserved_parts(raw, exported)
    assert text_spans(projection_api().project_docx(exported))[0].text == value
    with ZipFile(BytesIO(exported)) as archive:
        changed_info = archive.getinfo(MAIN)
        assert changed_info.file_size != old_size
        fields = extra_fields(changed_info.extra)
        assert [(tag, data) for tag, data in fields if tag != 1] == [
            (tag, data) for tag, data in extra_fields(original_info.extra) if tag != 1
        ]
        for tag, data in fields:
            if tag == 1:
                assert len(data) >= 16
                assert int.from_bytes(data[:8], "little") == changed_info.file_size
                assert int.from_bytes(data[8:16], "little") == changed_info.compress_size


def test_streamed_zip64_local_headers_and_data_descriptors_can_be_edited():
    class Stream(BytesIO):
        def seek(self, *args):
            raise OSError("Synthetic forward-only stream")

    xml = document_xml(paragraph("streamed text"))
    parts = zip_parts(raw_package(xml, extra_parts={"custom/opaque.bin": b"\x00unchanged\xff"}))
    stream = Stream()
    with ZipFile(stream, "w") as archive:
        archive.comment = b"streamed archive"
        for index, (name, payload) in enumerate(parts.items()):
            info = ZipInfo(name, date_time=(2025, 3, 4, 6, 8, 10))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100640 << 16
            info.internal_attr = 1
            info.comment = f"stream-part-{index}".encode()
            info.extra = b"\xfe\xca\x02\x00OK"
            with archive.open(info, "w", force_zip64=True) as output:
                output.write(payload)
    raw = stream.getvalue()
    with ZipFile(BytesIO(raw)) as archive:
        infos = archive.infolist()
        assert all(info.flag_bits & 8 for info in infos)
        for info in infos:
            offset = info.header_offset
            assert raw[offset + 18 : offset + 26] == b"\xff" * 8
            name_size = int.from_bytes(raw[offset + 26 : offset + 28], "little")
            extra_size = int.from_bytes(raw[offset + 28 : offset + 30], "little")
            start = offset + 30 + name_size
            assert any(tag == 1 for tag, _ in extra_fields(raw[start : start + extra_size]))
    span = text_spans(projection_api().project_docx(raw))[0]
    exported = edit_api().export_docx(raw, (edit(span, "changed streamed text"),))
    assert_preserved_parts(raw, exported)
    assert text_spans(projection_api().project_docx(exported))[0].text == "changed streamed text"
    attributes = (
        "filename",
        "date_time",
        "compress_type",
        "comment",
        "create_system",
        "external_attr",
        "internal_attr",
        "extra",
    )
    with ZipFile(BytesIO(exported)) as archive:
        assert archive.comment == b"streamed archive"
        assert [
            tuple(getattr(info, name) for name in attributes) for info in archive.infolist()
        ] == [tuple(getattr(info, name) for name in attributes) for info in infos]


def test_rich_control_document_edits_keep_every_other_part_and_tree_property():
    raw = FIXTURE.read_bytes()
    projected = projection_api().project_docx(raw)
    spans = text_spans(projected)
    hyperlink = next(span for span in spans if span.hyperlink is not None)
    table = next(block for block in projected.blocks if block.kind == "table")
    cell_span = table.rows[1].cells[0].blocks[0].spans[0]
    first = next(span for span in spans if span.hyperlink is None and span != cell_span)
    replacements = (
        (first, "Updated heading"),
        (hyperlink, "Updated link"),
        (cell_span, "Updated cell"),
    )
    edits = tuple(edit(span, value) for span, value in replacements)
    exported = edit_api().export_docx(raw, edits)
    before_xml, after_xml = assert_preserved_parts(raw, exported)
    before_root, after_root = ET.fromstring(before_xml), ET.fromstring(after_xml)
    for span, value in replacements:
        before_node, after_node = before_root, after_root
        for index in span.anchor.path:
            before_node, after_node = before_node[index], after_node[index]
        assert after_node.text == value
        assert after_node.attrib == {**before_node.attrib, f"{{{XML_NS}}}space": "preserve"}
        after_node.text = before_node.text
        after_node.attrib.clear()
        after_node.attrib.update(before_node.attrib)
    assert ET.tostring(after_root) == ET.tostring(before_root)
    assert len(text_spans(projection_api().project_docx(exported))) == len(spans)
    assert import_module("ara.docx_package").export_original(projected.source) == raw


def test_reprojected_output_can_be_edited_again_without_changing_source():
    raw, _ = package(paragraph("first"))
    first = text_spans(projection_api().project_docx(raw))[0]
    second_bytes = edit_api().export_docx(raw, (edit(first, "second"),))
    second = text_spans(projection_api().project_docx(second_bytes))[0]
    third_bytes = edit_api().export_docx(second_bytes, (edit(second, "third"),))
    assert first.anchor.path == second.anchor.path
    assert first.anchor.source_sha256 != second.anchor.source_sha256
    assert text_spans(projection_api().project_docx(raw))[0].text == "first"
    assert text_spans(projection_api().project_docx(second_bytes))[0].text == "second"
    assert text_spans(projection_api().project_docx(third_bytes))[0].text == "third"


def test_noop_works_for_other_valid_xml_encoding():
    raw, _ = package(paragraph("café"), encoding="iso-8859-1")
    span = text_spans(projection_api().project_docx(raw))[0]
    assert edit_api().export_docx(raw, ()) == raw
    assert edit_api().export_docx(raw, (edit(span, span.text),)) == raw


def test_edit_records_are_immutable_slotted_and_do_not_repr_text():
    raw, _ = package(paragraph("SYNTHETIC_SECRET_TEXT_391"))
    span = text_spans(projection_api().project_docx(raw))[0]
    record = edit(span, "SYNTHETIC_REPLACEMENT_847")
    limits = edit_api().EditLimits()
    assert "SYNTHETIC_SECRET_TEXT_391" not in repr(record)
    assert "SYNTHETIC_REPLACEMENT_847" not in repr(record)
    assert not hasattr(record, "__dict__") and not hasattr(limits, "__dict__")
    with pytest.raises(FrozenInstanceError):
        record.replacement_text = "changed"
    with pytest.raises(FrozenInstanceError):
        limits.max_edits = 2
    assert (limits.max_edits, limits.max_total_replacement_chars) == (1000, 1000000)
