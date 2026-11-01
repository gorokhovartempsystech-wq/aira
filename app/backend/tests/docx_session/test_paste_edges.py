"""Paste encoding, structural equality traps, amplification and preservation."""

import io
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.boundaries import BoundaryError
from ara.docx_package.editor import Caret, EditorError, EditorSelection, EditorSession, PasteLimits
from tests.acceptance.test_docx_boundaries import W, p, parts, replace, source


def at(e, lo, hi=None, index=0):
    s = e.snapshot()
    b = s.document.projection.blocks[index]
    return e.capture(
        EditorSelection(Caret(b.anchor, lo), Caret(b.anchor, lo if hi is None else hi)),
        expected_revision=s.document.revision,
    )


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16LE", "UTF-16BE"])
@pytest.mark.parametrize("strict", [False, True])
def test_local_namespace_and_encoding_on_bulk_paste(encoding, strict):
    data = source(
        f'<p xmlns="{W}" xmlns:q="urn:unused"><r xmlns:q="{W}">'
        "<q:rPr><q:i/></q:rPr><q:t>Alpha</q:t></r></p>"
    )
    changes = {}
    namespace = "http://purl.oclc.org/ooxml/wordprocessingml/main" if strict else W
    for name, value in parts(data).items():
        if name.startswith("word/") and name.endswith(".xml"):
            text = value.decode().replace(W, namespace)
            if "<?xml" in text:
                text = text.replace("UTF-8", encoding)
            else:
                text = f'<?xml version="1.0" encoding="{encoding}"?>' + text
            changes[name] = text.encode(encoding)
    data = replace(data, changes)
    e = EditorSession(data)
    at(e, 2)
    result = e.paste_text("X\nY\tZ", expected_revision=0)
    assert [p.text for p in result.document.projection.blocks] == ["AlX", "Y\tZpha"]
    root = ET.fromstring(parts(result.document.data)["word/document.xml"])
    assert len(root.findall(".//{" + namespace + "}tab")) == 1
    assert all(
        r.find("{" + namespace + "}rPr/{" + namespace + "}i") is not None
        for r in root.findall(".//{" + namespace + "}r")
    )


def test_same_projected_text_still_converts_soft_break_to_paragraph_boundary():
    data = source("<w:p><w:r><w:t>A</w:t><w:br/><w:t>B</w:t></w:r></w:p>")
    e = EditorSession(data)
    at(e, 0, 3)
    result = e.paste_text("A\nB", expected_revision=0)
    assert [p.text for p in result.document.projection.blocks] == ["A", "B"]
    assert result.document.revision == 1 and result.document.undo_depth == 1


def test_inclusive_limits_and_mutated_limits():
    e = EditorSession(source(p("Alpha")))
    assert (
        len(
            e.paste_text(
                "X\nY",
                expected_revision=0,
                paste_limits=PasteLimits(max_text_chars=3, max_new_paragraphs=1),
            ).document.projection.blocks
        )
        == 2
    )
    e = EditorSession(source(p("Alpha")))
    before = e.snapshot()
    for name in ("max_text_chars", "max_new_paragraphs"):
        limit = PasteLimits()
        object.__setattr__(limit, name, True)
        with pytest.raises(EditorError):
            e.paste_text("X", expected_revision=0, paste_limits=limit)
    assert e.snapshot() == before


def test_tab_xml_amplification_hits_package_budget_without_publish():
    data = source(p("Alpha"))
    e = EditorSession(data, limits=DocxLimits(max_xml_bytes=20000))
    before = e.snapshot()
    with pytest.raises(DocxError) as caught:
        e.paste_text("\t" * 1000, expected_revision=0)
    assert caught.value.code == "package_limit_exceeded" and e.snapshot() == before


def test_rich_zip_parts_metadata_and_protected_source_are_preserved():
    data = Path("tests/fixtures/docx/rich-source.docx").read_bytes()
    e = EditorSession(data)
    index = next(
        i
        for i, p in enumerate(e.snapshot().document.projection.blocks)
        if p.kind == "paragraph" and p.text == "Device classification"
    )
    at(e, 6, index=index)
    result = e.paste_text("X\nY", expected_revision=0)
    a, b = parts(data), parts(result.document.data)
    assert all(a[n] == b[n] for n in a if n != "word/document.xml")
    with ZipFile(io.BytesIO(data)) as old, ZipFile(io.BytesIO(result.document.data)) as new:
        assert old.namelist() == new.namelist()
        assert [(i.extra, i.external_attr, i.date_time) for i in old.infolist()] == [
            (i.extra, i.external_attr, i.date_time) for i in new.infolist()
        ]
    protected = source(p("Alpha") + '<w:bookmarkStart w:id="1" w:name="kept"/>')
    e = EditorSession(protected)
    before = e.snapshot()
    with pytest.raises(BoundaryError):
        e.paste_text("X\nY", expected_revision=0)
    assert e.snapshot() == before


def test_bulk_paste_is_inert_on_first_call():
    script = """
import builtins,io,os,socket,subprocess,logging
from pathlib import Path
from ara.docx_package.creation import create_docx
from ara.docx_package.editor import EditorSession
e=EditorSession(create_docx())
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes')):
    setattr(obj,name,forbidden)
s=e.paste_text('A\\tB\\r\\nC',expected_revision=0)
assert [p.text for p in s.document.projection.blocks]==['A\\tB','C']
assert e.undo(expected_revision=1).document.projection.blocks[0].text==''
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
