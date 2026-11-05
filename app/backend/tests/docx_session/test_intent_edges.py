"""Additional style resolution, encoding and inert composite-intent checks."""

import copy
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.editor import Caret, EditorError, EditorSelection, EditorSession
from tests.acceptance.test_docx_boundaries import W, parts, replace


def at_end(editor):
    p = editor.snapshot().document.projection.blocks[0]
    c = Caret(p.anchor, len(p.text))
    editor.capture(EditorSelection(c, c), expected_revision=0)


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16LE", "UTF-16BE"])
@pytest.mark.parametrize("strict", [False, True])
def test_composite_enter_keeps_namespace_encoding_and_other_parts(encoding, strict):
    data = create_docx((NewParagraph("Heading 😀", "heading1"),))
    changes = {}
    namespace = "http://purl.oclc.org/ooxml/wordprocessingml/main" if strict else W
    for name, content in parts(data).items():
        if name.startswith("word/") and name.endswith(".xml"):
            changes[name] = (
                content.decode().replace(W, namespace).replace("UTF-8", encoding).encode(encoding)
            )
    data = replace(data, changes)
    editor = EditorSession(data)
    at_end(editor)
    result = editor.enter(expected_revision=0)
    assert result.document.projection.blocks[1].style_id == "Normal"
    assert all(
        parts(data)[n] == parts(result.document.data)[n]
        for n in parts(data)
        if n != "word/document.xml"
    )
    assert namespace in parts(result.document.data)["word/document.xml"].decode(encoding)
    assert editor.undo(expected_revision=1).document.data == data


def test_custom_next_identifier_and_self_reference():
    data = create_docx((NewParagraph("Heading", "heading1"),))
    values = parts(data)
    styles = ET.fromstring(values["word/styles.xml"])
    ns = {"w": W}
    heading = styles.find('w:style[@w:styleId="Heading1"]', ns)
    heading.find("w:next", ns).set("{" + W + "}val", "Custom & Body")
    node = copy.deepcopy(styles.find('w:style[@w:styleId="Normal"]', ns))
    node.attrib.pop("{" + W + "}default")
    node.set("{" + W + "}styleId", "Custom & Body")
    styles.append(node)
    data = replace(data, {"word/styles.xml": ET.tostring(styles)})
    editor = EditorSession(data)
    at_end(editor)
    assert (
        editor.enter(expected_revision=0).document.projection.blocks[1].style_id == "Custom & Body"
    )
    heading.find("w:next", ns).set("{" + W + "}val", "Heading1")
    data = replace(data, {"word/styles.xml": ET.tostring(styles)})
    editor = EditorSession(data)
    at_end(editor)
    assert [p.style_id for p in editor.enter(expected_revision=0).document.projection.blocks] == [
        "Heading1",
        "Heading1",
    ]


def test_numbering_in_document_defaults_cannot_be_misidentified_as_plain_text():
    data = create_docx((NewParagraph("Heading", "heading1"),))
    styles = ET.fromstring(parts(data)["word/styles.xml"])
    node = styles.find(".//{" + W + "}pPrDefault/{" + W + "}pPr")
    num = ET.Element("{" + W + "}numPr")
    ET.SubElement(num, "{" + W + "}numId", {"{" + W + "}val": "1"})
    node.insert(1, num)
    data = replace(data, {"word/styles.xml": ET.tostring(styles)})
    editor = EditorSession(data)
    at_end(editor)
    before = editor.snapshot()
    with pytest.raises(EditorError):
        editor.enter(expected_revision=0)
    assert editor.snapshot() == before


def test_intents_are_inert_after_runtime_import():
    script = """
import builtins,io,os,socket,subprocess,logging
from pathlib import Path
from ara.docx_package.creation import create_docx,NewParagraph
from ara.docx_package.editor import EditorSession,Caret,EditorSelection
raw=create_docx((NewParagraph('Heading','heading1'),))
e=EditorSession(raw);p=e.snapshot().document.projection.blocks[0]
c=Caret(p.anchor,len(p.text));e.capture(EditorSelection(c,c),expected_revision=0)
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes')):
    setattr(obj,name,forbidden)
s=e.enter(expected_revision=0)
assert s.document.projection.blocks[1].style_id=='Normal'
assert e.undo(expected_revision=1).document.data==raw
"""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
