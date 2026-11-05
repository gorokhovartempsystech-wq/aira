"""Frozen D03-14: paragraph boundaries, source identity and safe rejection."""

import importlib
import io
from dataclasses import FrozenInstanceError
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.projection import SourceAnchor, project_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def api():
    return importlib.import_module("ara.docx_package.boundaries")


def parts(data):
    with ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def replace(data, changes):
    out = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as old, ZipFile(out, "w") as new:
        for info in old.infolist():
            new.writestr(info, changes.get(info.filename, old.read(info)))
    return out.getvalue()


def source(body):
    data = create_docx()
    xml = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'.encode()
    data = replace(data, {"word/document.xml": xml})
    project_docx(data)  # All fixtures must pass the unchanged source validator.
    return data


def p(text, properties=""):
    props = f"<w:pPr>{properties}</w:pPr>" if properties else ""
    return f'<w:p>{props}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def split(data, offset, index=0):
    paragraph = project_docx(data).blocks[index]
    return api().SplitParagraph(paragraph.anchor, paragraph.text, offset)


def join(data, left=0, right=1):
    blocks = project_docx(data).blocks
    return api().JoinParagraphs(
        blocks[left].anchor, blocks[right].anchor, blocks[left].text, blocks[right].text
    )


def texts(data):
    return [b.text for b in project_docx(data).blocks if b.kind == "paragraph"]


def reject(data, command, code, **kwargs):
    with pytest.raises(api().BoundaryError) as caught:
        api().export_boundary(data, command, **kwargs)
    assert caught.value.code == code
    assert str(caught.value) == caught.value.message
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize("text", ["", "a", "  A &amp; B 😀 е\u0301 &lt;x&gt;  "])
def test_split_every_code_point_and_compatible_join(text):
    data = source(p(text))
    original = texts(data)[0]
    for offset in range(len(original) + 1):
        result = api().export_boundary(data, split(data, offset))
        assert texts(result) == [original[:offset], original[offset:]]
        assert api().export_boundary(data, split(data, offset)) == result
        restored = api().export_boundary(result, join(result))
        assert texts(restored) == [original]


@pytest.mark.parametrize(
    "markup", ["<w:p/>", "<w:p><w:pPr/></w:p>", "<w:p><w:r><w:t/></w:r></w:p>"]
)
def test_selfclosing_and_empty_paragraphs(markup):
    data = source(markup)
    result = api().export_boundary(data, split(data, 0))
    assert texts(result) == ["", ""]
    assert texts(api().export_boundary(result, join(result))) == [""]


def test_native_controls_are_atoms_and_no_separator_is_invented():
    data = source(
        "<w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/>"
        "<w:t>C</w:t><w:cr/><w:t>D</w:t></w:r></w:p>"
    )
    original = "A\tB\nC\nD"
    assert texts(data) == [original]
    for offset in range(len(original) + 1):
        result = api().export_boundary(data, split(data, offset))
        assert texts(result) == [original[:offset], original[offset:]]
        assert texts(api().export_boundary(result, join(result))) == [original]


@pytest.mark.parametrize("style", ["heading1", "bullet", "numbered"])
def test_split_preserves_heading_and_existing_list_identity(style):
    data = create_docx((NewParagraph("Some text", style),))
    before = project_docx(data).blocks[0]
    result = api().export_boundary(data, split(data, 4))
    for block in project_docx(result).blocks:
        assert block.style_id == before.style_id
        assert block.numbering_id == before.numbering_id
        assert block.numbering_level == before.numbering_level
    assert all(parts(data)[n] == parts(result)[n] for n in parts(data) if n != "word/document.xml")


@pytest.mark.parametrize(
    "right",
    [
        '<w:pStyle w:val="Heading1"/>',
        '<w:spacing w:after="240"/>',
        '<w:pStyle w:val="Normal"/>',
        '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>',
    ],
)
def test_join_incompatible_direct_properties_is_atomic(right):
    data = source(p("Left") + p("Right", right))
    reject(data, join(data), "incompatible_paragraph_format")
    assert texts(data) == ["Left", "Right"]


@pytest.mark.parametrize("a,b", [("", "right"), ("left", ""), ("", "")])
def test_join_empty_paragraphs(a, b):
    data = source(p(a) + p(b))
    result = api().export_boundary(data, join(data))
    assert texts(result) == [a + b]


def test_invalid_identity_positions_and_nonadjacent_targets():
    data = source(p("One") + p("Two") + p("Three"))
    reject(data, split(data, 4), "invalid_position")
    reject(data, join(data, 0, 2), "nonadjacent_paragraphs")
    reject(data, join(data, 1, 0), "nonadjacent_paragraphs")
    reject(data, join(data, 0, 0), "nonadjacent_paragraphs")
    paragraph = project_docx(data).blocks[0]
    for anchor in (
        paragraph.spans[0].anchor,
        SourceAnchor(paragraph.anchor.source_sha256, "other.xml", paragraph.anchor.path),
    ):
        reject(data, api().SplitParagraph(anchor, paragraph.text, 1), "invalid_anchor")
    reject(data, api().SplitParagraph(paragraph.anchor, "SYNTHETIC_PRIVATE", 1), "text_mismatch")
    changed = api().export_boundary(data, split(data, 1))
    reject(changed, split(data, 1), "stale_source")


@pytest.mark.parametrize(
    "content",
    [
        '<w:r><w:br w:type="page"/></w:r>',
        '<w:r><w:br w:type="column"/></w:r>',
        '<w:r><w:br w:clear="all"/></w:r>',
        "<w:r><w:t>A\nB</w:t></w:r>",
        "<w:r><w:t>A\tB</w:t></w:r>",
        '<w:r><w:footnoteReference w:id="1"/></w:r>',
        "<w:pPr><w:pageBreakBefore/></w:pPr><w:r><w:t>A</w:t></w:r>",
        "<w:pPr><w:framePr/></w:pPr><w:r><w:t>A</w:t></w:r>",
        "<w:pPr><w:unknown/></w:pPr><w:r><w:t>A</w:t></w:r>",
        '<w:r><w:rPr><w:eastAsianLayout w:id="1"/></w:rPr><w:t>A</w:t></w:r>',
        '<w:r><w:rPr><w:b custom="unknown"/></w:rPr><w:t>A</w:t></w:r>',
        "<w:r><w:rPr><w:b/><w:b/></w:rPr><w:t>A</w:t></w:r>",
        "<w:r><w:t>A</w:t><!--annotation--></w:r>",
        "<w:r><w:t>A</w:t><?annotation value?></w:r>",
    ],
)
def test_unsupported_content_is_not_silently_dropped(content):
    data = source(f"<w:p>{content}</w:p>")
    reject(data, split(data, 0), "unsupported_boundary")


@pytest.mark.parametrize("attribute", ['custom="x"', 'xml:space="preserve"', 'xml:lang="en"'])
def test_unknown_paragraph_attributes_are_rejected(attribute):
    data = source(f"<w:p {attribute}><w:r><w:t>A</w:t></w:r></w:p>")
    reject(data, split(data, 0), "unsupported_boundary")


def test_global_ranges_protection_and_annotations_between_paragraphs():
    data = source(p("A") + '<w:bookmarkStart w:id="1" w:name="x"/>' + p("B"))
    reject(data, split(data, 0), "unsupported_boundary")
    data = source(p("A") + "<!--boundary-->" + p("B"))
    reject(data, join(data), "unsupported_boundary")
    data = create_docx((NewParagraph("Protected"),))
    settings = parts(data)["word/settings.xml"].replace(
        b"<w:compat>", b"<w:documentProtection/><w:compat>"
    )
    data = replace(data, {"word/settings.xml": settings})
    reject(data, split(data, 0), "unsupported_boundary")


def test_dtos_frozen_bypass_limits_and_lower_errors():
    data = source(p("SYNTHETIC_PRIVATE"))
    command = split(data, 1)
    assert "SYNTHETIC_PRIVATE" not in repr(command)
    with pytest.raises(FrozenInstanceError):
        command.offset = 2
    for name, value in (("offset", True), ("offset", -1), ("anchor", None), ("expected_text", 1)):
        value_command = split(data, 1)
        object.__setattr__(value_command, name, value)
        reject(data, value_command, "invalid_input")
    reject(data, object(), "invalid_input")
    for value in (True, 0, -1):
        with pytest.raises(api().BoundaryError):
            api().BoundaryLimits(value)
    # p,r,t are exactly three touched nodes.
    assert texts(api().export_boundary(data, command, boundary_limits=api().BoundaryLimits(3))) == [
        "S",
        "YNTHETIC_PRIVATE",
    ]
    reject(data, command, "boundary_limit_exceeded", boundary_limits=api().BoundaryLimits(2))
    with pytest.raises(DocxError):
        api().export_boundary(data, command, limits=DocxLimits(max_archive_bytes=1))


def test_inline_formats_survive_split_and_join():
    data = source(
        '<w:p><w:r><w:rPr><w:b/><w:color w:val="123456"/></w:rPr>'
        "<w:t>Bold</w:t><w:t> more</w:t></w:r>"
        "<w:r><w:rPr><w:i/></w:rPr><w:t>Italic</w:t></w:r></w:p>"
    )
    result = api().export_boundary(data, split(data, 2))
    root = ET.fromstring(parts(result)["word/document.xml"])
    assert len(root.findall(".//w:rPr/w:b", NS)) == 2
    assert len(root.findall(".//w:rPr/w:i", NS)) == 1
    joined = api().export_boundary(result, join(result))
    assert texts(joined) == ["Bold moreItalic"]
    assert len(ET.fromstring(parts(joined)["word/document.xml"]).findall(".//w:rPr/w:b", NS)) == 2
