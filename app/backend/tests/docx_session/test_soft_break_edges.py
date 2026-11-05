"""Native break namespaces, preservation, conservative gates and inert calls."""

import io
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package.boundaries import BoundaryError
from ara.docx_package.editor import Caret, EditorError, EditorSelection, EditorSession
from ara.docx_package.projection import ProjectionError, ProjectionLimits
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
def test_break_uses_valid_namespace_scope_and_preserves_original_encoding(encoding, strict):
    data = source(
        f'<p xmlns="{W}" xmlns:q="urn:unused"><r xmlns:q="{W}">'
        "<q:rPr><q:i/></q:rPr><q:t>Alpha</q:t></r></p>"
    )
    namespace = "http://purl.oclc.org/ooxml/wordprocessingml/main" if strict else W
    changes = {}
    for name, value in parts(data).items():
        if name.startswith("word/") and name.endswith(".xml"):
            text = value.decode().replace(W, namespace)
            text = (
                text.replace("UTF-8", encoding)
                if "<?xml" in text
                else f'<?xml version="1.0" encoding="{encoding}"?>' + text
            )
            changes[name] = text.encode(encoding)
    data = replace(data, changes)
    e = EditorSession(data)
    at(e, 2)
    result = e.insert_soft_break(expected_revision=0)
    assert [b.text for b in result.document.projection.blocks] == ["Al\npha"]
    xml = parts(result.document.data)["word/document.xml"]
    assert encoding in xml.decode(encoding)
    root = ET.fromstring(xml)
    assert len(root.findall(".//{" + namespace + "}br")) == 1
    assert all(
        r.find("{" + namespace + "}rPr/{" + namespace + "}i") is not None
        for r in root.findall(".//{" + namespace + "}r")
    )


@pytest.mark.parametrize("lo,hi", [(4, 8), (8, 4)])
def test_range_direction_does_not_change_break_template(lo, hi):
    e = EditorSession(
        source(
            "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r>"
            "<w:r><w:rPr><w:i/></w:rPr><w:t>Italic</w:t></w:r></w:p>"
        )
    )
    at(e, lo, hi)
    result = e.insert_soft_break(expected_revision=0)
    assert result.document.projection.blocks[0].text == "Bold\nic"
    root = ET.fromstring(parts(result.document.data)["word/document.xml"])
    ns = {"w": W}
    br = next(r for r in root.findall(".//w:r", ns) if r.find("w:br", ns) is not None)
    assert br.find("w:rPr/w:i", ns) is not None
    assert br.find("w:rPr/w:b", ns) is None


def test_empty_paragraph_mark_format_and_repeated_breaks_survive_branching_history():
    data = source("<w:p><w:pPr><w:rPr><w:i/></w:rPr></w:pPr></w:p>")
    e = EditorSession(data)
    e.insert_soft_break(expected_revision=0)
    two = e.insert_soft_break(expected_revision=1)
    assert two.document.projection.blocks[0].text == "\n\n"
    e.undo(expected_revision=2)
    branch = e.insert_text("Typed", expected_revision=3)
    assert branch.document.projection.blocks[0].text == "\nTyped"
    assert branch.document.redo_depth == 0 and branch.position_id > two.position_id
    ns = {"w": W}
    root = ET.fromstring(parts(branch.document.data)["word/document.xml"])
    assert all(r.find("w:rPr/w:i", ns) is not None for r in root.findall(".//w:r", ns))
    e.undo(expected_revision=4)
    assert e.undo(expected_revision=5).document.data == data


def test_rich_parts_metadata_and_unselected_paragraphs_stay_exact():
    data = Path("tests/fixtures/docx/rich-source.docx").read_bytes()
    e = EditorSession(data)
    index = next(
        i
        for i, b in enumerate(e.snapshot().document.projection.blocks)
        if b.kind == "paragraph" and b.text == "Device classification"
    )
    at(e, 6, index=index)
    result = e.insert_soft_break(expected_revision=0)
    old, new = parts(data), parts(result.document.data)
    assert all(old[n] == new[n] for n in old if n != "word/document.xml")
    with ZipFile(io.BytesIO(data)) as a, ZipFile(io.BytesIO(result.document.data)) as b:
        assert a.namelist() == b.namelist()
        assert [(i.extra, i.external_attr, i.date_time) for i in a.infolist()] == [
            (i.extra, i.external_attr, i.date_time) for i in b.infolist()
        ]
    # The untouched main prefix/suffix also retain lexical bytes, including drawing/table XML.
    original_p = b"<w:t>Device classification</w:t>"
    assert original_p in old["word/document.xml"]
    left = old["word/document.xml"].split(original_p)[0].rsplit(b"<w:p", 1)[0]
    assert new["word/document.xml"].startswith(left)
    assert e.undo(expected_revision=1).document.data == data


@pytest.mark.parametrize(
    "markup",
    [
        p("Alpha") + '<w:bookmarkStart w:id="1" w:name="keep"/>',
        '<w:p><w:r><w:t>A</w:t><w:br w:type="page"/><w:t>B</w:t></w:r></w:p>',
    ],
)
def test_protected_or_opaque_source_is_not_deleted_to_insert_break(markup):
    e = EditorSession(source(markup))
    before = at(e, 0)
    with pytest.raises(BoundaryError):
        e.insert_soft_break(expected_revision=0)
    assert e.snapshot() == before


def test_field_only_source_is_rejected_before_any_editable_selection_exists():
    data = source(
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:t>A</w:t><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    with pytest.raises(EditorError) as caught:
        EditorSession(data)
    assert caught.value.code == "invalid_selection"


def test_projected_node_growth_failure_is_atomic():
    e = EditorSession(source(p("Alpha")), projection_limits=ProjectionLimits(max_nodes=5))
    before = at(e, 2)
    with pytest.raises(ProjectionError):
        e.insert_soft_break(expected_revision=0)
    assert e.snapshot() == before


def test_first_break_call_does_not_open_files_network_processes_or_read_environment():
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
s=e.insert_soft_break(expected_revision=0)
assert len(s.document.projection.blocks)==1
assert s.document.projection.blocks[0].text=='\\n'
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
