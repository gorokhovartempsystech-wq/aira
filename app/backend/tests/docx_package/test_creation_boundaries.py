"""Additional creation limits and interoperability cases beyond frozen acceptance."""

import io
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package.creation import CreationError, CreationLimits, NewParagraph, create_docx
from ara.docx_package.projection import project_docx


def test_subclasses_and_uninitialized_records_are_not_accepted():
    class Text(str):
        pass

    class Records(tuple):
        pass

    class Paragraph(NewParagraph):
        pass

    class Limits(CreationLimits):
        pass

    for call in (
        lambda: NewParagraph(Text("text")),
        lambda: NewParagraph("text", Text("body")),
        lambda: create_docx(Records()),
        lambda: create_docx((Paragraph(),)),
        lambda: create_docx(creation_limits=Limits()),
        lambda: create_docx((object.__new__(NewParagraph),)),
        lambda: create_docx(creation_limits=object.__new__(CreationLimits)),
    ):
        with pytest.raises(CreationError) as caught:
            call()
        assert caught.value.code == "invalid_input"


def test_separated_numbering_survives_existing_text_edit_without_style_loss():
    from ara.docx_package.editing import TextEdit, export_docx

    styles = ("numbered", "bullet", "numbered", "heading1", "numbered")
    raw = create_docx(tuple(NewParagraph("same", style) for style in styles))
    before = project_docx(raw)
    numbered_ids = [p.numbering_id for p in before.blocks if p.style_id == "ListNumber"]
    assert len(set(numbered_ids)) == 3
    span = before.blocks[2].spans[0]
    changed = export_docx(raw, (TextEdit(span.anchor, "same", "Обновлено"),))
    after = project_docx(changed)
    assert [p.text for p in after.blocks] == ["same", "same", "Обновлено", "same", "same"]
    assert [p.numbering_id for p in after.blocks] == [p.numbering_id for p in before.blocks]
    with ZipFile(io.BytesIO(changed)) as package:
        xml = ET.fromstring(package.read("word/document.xml"))
    assert len(xml.findall(".//{*}numPr")) == 4


def test_limits_include_empty_paragraphs_and_escaping_does_not_consume_text_budget():
    paragraphs = tuple(NewParagraph() for _ in range(3))
    assert (
        len(project_docx(create_docx(paragraphs, creation_limits=CreationLimits(3, 1))).blocks) == 3
    )
    with pytest.raises(CreationError):
        create_docx(paragraphs, creation_limits=CreationLimits(2, 1))
    assert (
        project_docx(create_docx((NewParagraph("&<>"),), creation_limits=CreationLimits(1, 3)))
        .blocks[0]
        .text
        == "&<>"
    )
