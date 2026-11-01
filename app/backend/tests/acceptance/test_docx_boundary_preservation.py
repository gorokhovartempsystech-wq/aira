"""Frozen D03-14: lexical preservation, namespaces and inert operations."""

import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_boundaries import W, api, join, p, parts, replace, source, split, texts

STRICT = "http://purl.oclc.org/ooxml/wordprocessingml/main"


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16LE", "UTF-16BE"])
@pytest.mark.parametrize("namespace", [W, STRICT])
def test_namespace_and_encoding_preservation(encoding, namespace):
    data = source(p("Outside") + p("  A 😀 &amp; Б  ") + p("Tail"))
    main = parts(data)["word/document.xml"].decode().replace(W, namespace)
    main = f'<?xml version="1.0" encoding="{encoding}"?>' + main
    data = replace(data, {"word/document.xml": main.encode(encoding)})
    old = parts(data)
    result = api().export_boundary(data, split(data, 5, 1))
    assert texts(result) == ["Outside", "  A 😀", " & Б  ", "Tail"]
    assert all(old[n] == parts(result)[n] for n in old if n != "word/document.xml")
    final = api().export_boundary(result, join(result, 1, 2))
    assert texts(final) == texts(data)
    assert p("Outside").encode(encoding) in parts(result)["word/document.xml"]
    assert p("Tail").encode(encoding) in parts(result)["word/document.xml"]


def test_rehome_local_default_namespaces_and_preserve_identity():
    data = source(
        f'<p xmlns="{W}" xmlns:q="{W}" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'w14:paraId="12345678"><r><rPr><b/></rPr><t xml:space="preserve">Local text</t></r></p>'
    )
    result = api().export_boundary(data, split(data, 3))
    root = ET.fromstring(parts(result)["word/document.xml"])
    ids = [
        n.get("{http://schemas.microsoft.com/office/word/2010/wordml}paraId")
        for n in root.findall(f"{{{W}}}body/{{{W}}}p")
    ]
    assert ids == ["12345678", None]
    assert len(root.findall(f".//{{{W}}}b")) == 2
    assert texts(api().export_boundary(result, join(result))) == ["Local text"]
    # Same Word namespace, different prefixes and a conflicting unused binding.
    data = source(
        f'<a:p xmlns:a="{W}" xmlns:z="urn:left"><a:r><a:t>Left</a:t></a:r></a:p>'
        f'<z:p xmlns:z="{W}" xmlns="{W}"><r><rPr><i/></rPr><t>Right</t></r></z:p>'
    )
    result = api().export_boundary(data, join(data))
    assert texts(result) == ["LeftRight"]
    assert len(ET.fromstring(parts(result)["word/document.xml"]).findall(f".//{{{W}}}i")) == 1


def test_all_property_groups_are_preserved_without_restyling():
    props = (
        '<w:pStyle w:val="Normal"/><w:keepNext/><w:keepLines/><w:widowControl/>'
        '<w:spacing w:after="240" w:line="276"/><w:ind w:left="50" w:firstLine="10"/>'
        '<w:jc w:val="left"/><w:outlineLvl w:val="0"/>'
        '<w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs><w:contextualSpacing/>'
        '<w:bidi w:val="0"/><w:snapToGrid/><w:suppressAutoHyphens/><w:adjustRightInd/>'
        '<w:rPr><w:rFonts w:ascii="Arial" w:cstheme="minorBidi"/>'
        '<w:color w:val="123456"/><w:sz w:val="22"/><w:u w:val="single"/>'
        '<w:lang w:val="ru-RU"/><w:vertAlign w:val="baseline"/></w:rPr>'
    )
    data = source(p("Text", props))
    result = api().export_boundary(data, split(data, 2))
    assert parts(result)["word/document.xml"].count(props.encode()) == 2
    assert texts(api().export_boundary(result, join(result))) == ["Text"]


def test_unchanged_ranges_zip_metadata_and_rich_parts():
    import io
    from pathlib import Path
    from zipfile import ZipFile

    fixture = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"
    assert fixture.is_file()
    data = fixture.read_bytes()
    view = __import__("ara.docx_package.projection", fromlist=["project_docx"]).project_docx(data)
    index = next(
        i
        for i, b in enumerate(view.blocks)
        if b.kind == "paragraph" and b.text == "Device classification"
    )
    result = api().export_boundary(data, split(data, 6, index))
    old, new = parts(data), parts(result)
    assert all(old[n] == new[n] for n in old if n != "word/document.xml")
    with ZipFile(io.BytesIO(data)) as a, ZipFile(io.BytesIO(result)) as b:
        assert a.namelist() == b.namelist() and a.comment == b.comment
        for x, y in zip(a.infolist(), b.infolist()):
            assert (x.date_time, x.extra, x.external_attr, x.comment) == (
                y.date_time,
                y.extra,
                y.external_attr,
                y.comment,
            )


def test_import_and_api_are_inert():
    script = """
import builtins,io,os,logging,socket,subprocess,importlib
from pathlib import Path
from ara.docx_package.creation import create_docx,NewParagraph
from ara.docx_package.projection import project_docx
raw=create_docx((NewParagraph('Synthetic'),));p=project_docx(raw).blocks[0]
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(Path,'read_bytes'),(os,'getenv'),
                 (socket,'socket'),(subprocess,'Popen'),(logging.Logger,'_log')):
    setattr(obj,name,forbidden)
m=importlib.import_module('ara.docx_package.boundaries')
result=m.export_boundary(raw,m.SplitParagraph(p.anchor,p.text,3))
a,b=project_docx(result).blocks
result=m.export_boundary(result,m.JoinParagraphs(a.anchor,b.anchor,a.text,b.text))
assert project_docx(result).blocks[0].text=='Synthetic'
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
