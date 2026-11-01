"""D03-12: encoding, inherited lists, ambiguous parts and lexical boundaries."""

import io
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.formatting import (
    FormatLimits,
    FormattingError,
    ParagraphFormat,
    export_formats,
)
from ara.docx_package.projection import project_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STRICT = "http://purl.oclc.org/ooxml/wordprocessingml/main"
NS = {"w": W}


def parts(data):
    with ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def replace(data, edits):
    result = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as old, ZipFile(result, "w") as new:
        for info in old.infolist():
            new.writestr(info, edits.get(info.filename, old.read(info)))
    return result.getvalue()


def cmd(data, index=0, style="Heading1", kind="none", identity=None):
    p = project_docx(data).blocks[index]
    return ParagraphFormat(p.anchor, p.text, style, kind, identity)


def rejects(data, *, kind="none", identity=None, code="unsupported_format", **kwargs):
    with pytest.raises(FormattingError) as caught:
        export_formats(data, (cmd(data, kind=kind, identity=identity),), **kwargs)
    assert caught.value.code == code


@pytest.mark.parametrize("namespace", [W, STRICT])
@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16LE", "UTF-16BE"])
def test_native_formatting_with_strict_and_utf16_parts(namespace, encoding):
    data = create_docx((NewParagraph("Свет 😀 & <relay>"), NewParagraph("Продолжение")))
    edits = {}
    for name, content in parts(data).items():
        if name.startswith("word/") and name.endswith(".xml"):
            text = content.decode().replace(W, namespace).replace("UTF-8", encoding)
            edits[name] = text.encode(encoding)
    data = replace(data, edits)
    before = parts(data)
    result = export_formats(data, (cmd(data, kind="numbered"),))
    after = parts(result)
    assert [p.text for p in project_docx(result).blocks] == [
        p.text for p in project_docx(data).blocks
    ]
    assert project_docx(result).blocks[0].numbering_id is not None
    assert after["word/styles.xml"] == before["word/styles.xml"]
    assert after["word/document.xml"].decode(encoding).count("<w:r>") == 2
    assert namespace in after["word/numbering.xml"].decode(encoding)


@pytest.mark.parametrize("kind", ["styles", "numbering"])
def test_unlinked_or_repeated_relationship_is_not_used(kind):
    data = create_docx()
    name = "word/_rels/document.xml.rels"
    root = ET.fromstring(parts(data)[name])
    link = next(n for n in root if n.get("Type").endswith("/" + kind))
    original = ET.tostring(link)
    root.remove(link)
    unlinked = replace(data, {name: ET.tostring(root)})
    rejects(unlinked, kind="numbered" if kind == "numbering" else "none")
    link.set("Id", "duplicate")
    root.append(ET.fromstring(original))
    root.append(link)
    duplicate = replace(data, {name: ET.tostring(root)})
    rejects(duplicate, kind="numbered" if kind == "numbering" else "none")


def test_level_zero_override_determines_effective_list_kind():
    data = create_docx()
    name = "word/numbering.xml"
    original = parts(data)[name]
    needle = b'<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    replacement = (
        b'<w:num w:numId="1"><w:abstractNumId w:val="0"/>'
        b'<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0">'
        b'<w:start w:val="1"/><w:numFmt w:val="decimal"/>'
        b'<w:lvlText w:val="%1."/></w:lvl></w:lvlOverride></w:num>'
    )
    assert needle in original
    data = replace(data, {name: original.replace(needle, replacement)})
    result = export_formats(data, (cmd(data, kind="numbered", identity="1"),))
    assert project_docx(result).blocks[0].numbering_id == "1"
    assert parts(result)[name] == parts(data)[name]
    rejects(data, kind="bullet", identity="1")
    # A linked style requires inheritance resolution beyond this contract.
    changed = parts(data)[name].replace(
        b'<w:abstractNum w:abstractNumId="0">',
        b'<w:abstractNum w:abstractNumId="0"><w:numStyleLink w:val="Other"/>',
    )
    rejects(replace(data, {name: changed}), kind="numbered", identity="1")


def test_ppr_insertion_order_and_unselected_runs_are_exact():
    data = create_docx((NewParagraph("first"), NewParagraph("second")))
    name = "word/document.xml"
    old = parts(data)[name]
    kept = b'<w:keepNext/><w:keepLines/><w:spacing w:before="123"/><w:jc w:val="right"/>'
    old = old.replace(b'<w:pStyle w:val="Normal"/>', kept, 1)
    data = replace(data, {name: old})
    after = parts(export_formats(data, (cmd(data, kind="bullet"),)))[name]
    props = ET.fromstring(after).find("w:body/w:p/w:pPr", NS)
    assert [n.tag.rsplit("}", 1)[-1] for n in props] == [
        "pStyle",
        "keepNext",
        "keepLines",
        "numPr",
        "spacing",
        "jc",
    ]
    assert b'<w:spacing w:before="123"/><w:jc w:val="right"/>' in after
    assert b'<w:r><w:t xml:space="preserve">first</w:t></w:r>' in after
    assert old[old.index(b"</w:p>") + 6 :] == after[after.index(b"</w:p>") + 6 :]


def test_aux_depth_and_id_exhaustion_are_bounded():
    data = create_docx()
    rejects(data, code="format_limit_exceeded", format_limits=FormatLimits(max_aux_depth=1))
    name = "word/numbering.xml"
    original = parts(data)[name]
    changed = original.replace(b'w:numId="1"', b'w:numId="2147483647"')
    assert changed != original
    rejects(replace(data, {name: changed}), kind="numbered")


def test_selfclosing_numbering_and_cleanup_order_preserve_attributes():
    data = create_docx()
    name = "word/numbering.xml"
    blank = f'<w:numbering xmlns:w="{W}" custom="kept"/>'.encode()
    data = replace(data, {name: blank})
    result = export_formats(data, (cmd(data, kind="bullet"),))
    root = ET.fromstring(parts(result)[name])
    assert root.get("custom") == "kept"
    assert project_docx(result).blocks[0].numbering_id == "1"
    content = parts(result)[name].replace(
        b"</w:numbering>", b'<w:numIdMacAtCleanup w:val="2"/></w:numbering>'
    )
    data = replace(result, {name: content})
    result = export_formats(data, (cmd(data, kind="numbered"),))
    assert [n.tag.rsplit("}", 1)[-1] for n in ET.fromstring(parts(result)[name])][-1] == (
        "numIdMacAtCleanup"
    )
