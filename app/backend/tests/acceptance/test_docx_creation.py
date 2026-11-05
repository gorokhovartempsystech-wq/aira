"""D03-09 frozen acceptance: exact new content, Word semantics and safe limits."""

import importlib
import io
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package import DocxError, DocxLimits, export_original, open_docx
from ara.docx_package.projection import ProjectionError, ProjectionLimits, project_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
PRIVATE = "SYNTHETIC_CREATION_4362"
ROOT = Path(__file__).resolve().parents[2]


def api():
    return importlib.import_module("ara.docx_package.creation")


def parts(data):
    with ZipFile(io.BytesIO(data)) as package:
        return {name: package.read(name) for name in package.namelist()}


def reject(call, code="invalid_input"):
    with pytest.raises(api().CreationError) as caught:
        call()
    assert caught.value.code == code
    assert str(caught.value) == caught.value.message
    assert caught.value.message and PRIVATE not in repr(caught.value)
    assert caught.value.__cause__ is None


def test_blank_is_one_editable_empty_paragraph_without_placeholder():
    data = api().create_docx()
    assert type(data) is bytes
    view = project_docx(data)
    assert [p.text for p in view.blocks] == [""]
    assert view.blocks[0].style_id == "Normal"
    assert [(s.kind, s.text) for s in view.blocks[0].spans] == [("text", "")]
    assert not view.has_unprojected_content
    assert export_original(open_docx(data)) == data


@pytest.mark.parametrize(
    "text", ["", '  Реле & <свет> "x"  ', "e\u0301 é 😀 \U00010000", "\n\tA\t\n\n B \t"]
)
def test_exact_text_and_controls_roundtrip(text):
    data = api().create_docx((api().NewParagraph(text),))
    paragraph = project_docx(data).blocks[0]
    assert paragraph.text == text
    markup = ET.fromstring(parts(data)["word/document.xml"])
    assert len(markup.findall(".//w:br", NS)) == text.count("\n")
    assert len(markup.findall(".//w:tab", NS)) == text.count("\t")
    assert all(
        n.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
        for n in markup.findall(".//w:t", NS)
    )


def test_semantic_paragraph_order_native_lists_and_restart():
    styles = (
        "title",
        "body",
        "heading1",
        "heading2",
        "heading3",
        "bullet",
        "bullet",
        "numbered",
        "numbered",
        "body",
        "numbered",
    )
    data = api().create_docx(
        tuple(api().NewParagraph(f"p{i}", style) for i, style in enumerate(styles))
    )
    view = project_docx(data)
    assert [p.text for p in view.blocks] == [f"p{i}" for i in range(len(styles))]
    assert [p.style_id for p in view.blocks] == [
        "Title",
        "Normal",
        "Heading1",
        "Heading2",
        "Heading3",
        "ListBullet",
        "ListBullet",
        "ListNumber",
        "ListNumber",
        "Normal",
        "ListNumber",
    ]
    assert view.blocks[5].numbering_id == view.blocks[6].numbering_id
    assert view.blocks[7].numbering_id == view.blocks[8].numbering_id
    assert view.blocks[10].numbering_id != view.blocks[8].numbering_id
    assert view.blocks[5].numbering_id != view.blocks[7].numbering_id
    numbering = ET.fromstring(parts(data)["word/numbering.xml"])
    for paragraph, fmt, marker in (
        (view.blocks[5], "bullet", "•"),
        (view.blocks[7], "decimal", "%1."),
        (view.blocks[10], "decimal", "%1."),
    ):
        assert paragraph.numbering_level == "0"
        instance = numbering.find(f"w:num[@w:numId='{paragraph.numbering_id}']", NS)
        abstract_id = instance.find("w:abstractNumId", NS).get(f"{{{W}}}val")
        level = numbering.find(f"w:abstractNum[@w:abstractNumId='{abstract_id}']/w:lvl", NS)
        assert level.find("w:numFmt", NS).get(f"{{{W}}}val") == fmt
        assert level.find("w:lvlText", NS).get(f"{{{W}}}val") == marker
        if fmt == "decimal":
            assert instance.find("w:lvlOverride/w:startOverride", NS).get(f"{{{W}}}val") == "1"


def test_template_typography_page_and_heading_semantics():
    items = parts(api().create_docx())
    document = ET.fromstring(items["word/document.xml"])
    section = document.find("w:body/w:sectPr", NS)
    assert section.find("w:pgSz", NS).attrib == {f"{{{W}}}w": "11906", f"{{{W}}}h": "16838"}
    margins = section.find("w:pgMar", NS)
    assert all(
        margins.get(f"{{{W}}}{side}") == "1134" for side in ("top", "bottom", "left", "right")
    )
    styles = ET.fromstring(items["word/styles.xml"])
    normal = styles.find("w:style[@w:styleId='Normal']", NS)
    assert normal.get(f"{{{W}}}default") == "1"
    assert normal.find("w:rPr/w:sz", NS).get(f"{{{W}}}val") == "22"
    assert set(normal.find("w:rPr/w:rFonts", NS).attrib.values()) == {"Arial"}
    spacing = normal.find("w:pPr/w:spacing", NS)
    assert spacing.get(f"{{{W}}}line") == "276" and spacing.get(f"{{{W}}}lineRule") == "auto"
    for index, size in enumerate((32, 26, 22), start=1):
        style = styles.find(f"w:style[@w:styleId='Heading{index}']", NS)
        assert style.find("w:pPr/w:outlineLvl", NS).get(f"{{{W}}}val") == str(index - 1)
        assert style.find("w:rPr/w:sz", NS).get(f"{{{W}}}val") == str(size)
        assert style.find("w:pPr/w:keepNext", NS) is not None
        assert style.find("w:pPr/w:keepLines", NS) is not None
        assert style.find("w:rPr/w:color", NS).get(f"{{{W}}}val") == "000000"
    title = styles.find("w:style[@w:styleId='Title']", NS)
    assert title.find("w:rPr/w:sz", NS).get(f"{{{W}}}val") == "44"
    assert not styles.findall(".//w:pBdr", NS)


def test_deterministic_minimal_package_without_private_or_external_metadata():
    one = api().create_docx((api().NewParagraph("Document"),))
    assert api().create_docx((api().NewParagraph("Document"),)) == one
    expected = [
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/_rels/document.xml.rels",
        "word/styles.xml",
        "word/numbering.xml",
        "word/settings.xml",
    ]
    with ZipFile(io.BytesIO(one)) as package:
        assert package.namelist() == expected
        assert not package.comment
        assert all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in package.infolist())
    source = open_docx(one)
    assert all(r.target_mode == "Internal" for r in source.relationships)
    assert {r.resolved_part for r in source.relationships} == {
        "word/document.xml",
        "word/styles.xml",
        "word/numbering.xml",
        "word/settings.xml",
    }
    settings = ET.fromstring(parts(one)["word/settings.xml"])
    assert settings.find("w:trackRevisions", NS) is None
    assert settings.find("w:documentProtection", NS) is None


def test_dtos_are_frozen_slotted_and_repr_does_not_print_text():
    paragraph = api().NewParagraph(PRIVATE)
    limits = api().CreationLimits()
    assert PRIVATE not in repr(paragraph)
    assert not hasattr(paragraph, "__dict__") and not hasattr(limits, "__dict__")
    assert (limits.max_paragraphs, limits.max_text_chars) == (1000, 1000000)
    with pytest.raises(FrozenInstanceError):
        paragraph.text = "changed"
    with pytest.raises(FrozenInstanceError):
        limits.max_paragraphs = 2


@pytest.mark.parametrize("value", [None, [], {}, "text", b"text", (None,), ("text",)])
def test_strict_container_and_paragraph_types(value):
    reject(lambda: api().create_docx(value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", None),
        ("text", b"x"),
        ("text", 1),
        ("style", None),
        ("style", "Heading1"),
        ("style", ""),
        ("style", []),
    ],
)
def test_frozen_bypass_is_revalidated(field, value):
    paragraph = api().NewParagraph(PRIVATE)
    object.__setattr__(paragraph, field, value)
    reject(lambda: api().create_docx((paragraph,)))


@pytest.mark.parametrize(
    "text",
    ["\x00", "\x01", "\x0b", "\x0c", "\x1f", "\r", "\r\n", "\ud800", "\udfff", "\ufffe", "\uffff"],
)
def test_xml_unsafe_or_ambiguous_text_rejected_without_normalization(text):
    reject(lambda: api().create_docx((api().NewParagraph(PRIVATE + text),)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_paragraphs", 0),
        ("max_paragraphs", True),
        ("max_paragraphs", 1.5),
        ("max_text_chars", -1),
        ("max_text_chars", None),
        ("max_text_chars", "4"),
    ],
)
def test_mutated_creation_limits_revalidated(field, value):
    limits = api().CreationLimits()
    object.__setattr__(limits, field, value)
    reject(lambda: api().create_docx(creation_limits=limits))


def test_limits_count_unicode_and_blank_paragraph_inclusively():
    limits = api().CreationLimits(max_paragraphs=2, max_text_chars=3)
    paragraphs = (api().NewParagraph("😀&"), api().NewParagraph("e"))
    assert [
        p.text for p in project_docx(api().create_docx(paragraphs, creation_limits=limits)).blocks
    ] == ["😀&", "e"]
    reject(
        lambda: api().create_docx(paragraphs + (api().NewParagraph(),), creation_limits=limits),
        "generation_limit_exceeded",
    )
    reject(
        lambda: api().create_docx((api().NewParagraph("😀&ee"),), creation_limits=limits),
        "generation_limit_exceeded",
    )
    assert api().create_docx(creation_limits=api().CreationLimits(1, 1))
    reject(lambda: api().create_docx(creation_limits={}))


def test_existing_package_and_projection_limits_still_apply():
    with pytest.raises(DocxError) as caught:
        api().create_docx(limits=DocxLimits(max_archive_bytes=1))
    assert caught.value.code == "package_limit_exceeded"
    with pytest.raises(ProjectionError) as caught:
        api().create_docx(projection_limits=ProjectionLimits(max_nodes=1))
    assert caught.value.code == "projection_limit_exceeded"
    with pytest.raises(DocxError):
        api().create_docx(limits={})
    with pytest.raises(ProjectionError):
        api().create_docx(projection_limits={})


@pytest.mark.parametrize("text", ["", "Before"])
def test_generated_file_can_use_existing_session_edits_and_exact_undo(text):
    from ara.docx_package.ranges import RangeEdit, TextPosition
    from ara.docx_package.session import DocxSession

    data = api().create_docx((api().NewParagraph(text),))
    session = DocxSession(data)
    snapshot = session.snapshot()
    span = snapshot.projection.blocks[0].spans[0]
    edit = RangeEdit(
        TextPosition(span.anchor, 0), TextPosition(span.anchor, len(text)), text, "After 😀"
    )
    changed = session.apply((edit,), expected_revision=0)
    assert changed.projection.blocks[0].text == "After 😀"
    a, b = parts(data), parts(changed.data)
    assert all(a[name] == b[name] for name in a if name != "word/document.xml")
    assert session.undo(expected_revision=1).data == data
    assert session.redo(expected_revision=2).data == changed.data


def test_import_and_creation_have_no_external_side_effects():
    script = """
import builtins, importlib, io, json, logging, os, socket, subprocess, sys, tempfile
from pathlib import Path
import urllib.request
import ara.docx_package.projection
def forbidden(*args, **kwargs):
    raise AssertionError("External side effect")
for target, name in (
    (builtins,"open"),(io,"open"),(socket,"socket"),(socket,"create_connection"),
    (subprocess,"Popen"),(subprocess,"run"),(tempfile,"TemporaryFile"),
    (tempfile,"NamedTemporaryFile"),(tempfile,"mkstemp"),(urllib.request,"urlopen"),
    (os,"getenv"),(logging.Logger,"_log"),
):
    setattr(target,name,forbidden)
module=importlib.import_module("ara.docx_package.creation")
result=module.create_docx((module.NewParagraph("SYNTHETIC_CREATION_4362"),))
assert type(result) is bytes
print(json.dumps({"size":len(result)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PATH": str(Path(sys.executable).parent), "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["size"] > 0
    assert PRIVATE not in result.stdout + result.stderr
