"""Typing namespace scope, controls, protection and inclusive size boundaries."""

import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from ara.docx_package.boundaries import BoundaryError
from ara.docx_package.creation import create_docx
from ara.docx_package.editor import Caret, EditorSelection, EditorSession
from tests.acceptance.test_docx_boundaries import W, parts, replace, source


def at(e, offset, index=0):
    p = e.snapshot().document.projection.blocks[index]
    c = Caret(p.anchor, offset)
    return e.capture(EditorSelection(c, c), expected_revision=e.snapshot().document.revision)


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16LE", "UTF-16BE"])
def test_property_local_namespace_fallback_survives_text_insertion(encoding):
    data = source(f'<w:p><w:pPr xmlns:q="{W}"><q:rPr><q:b/></q:rPr></w:pPr></w:p>')
    raw = parts(data)["word/document.xml"].decode()
    raw = (f'<?xml version="1.0" encoding="{encoding}"?>' + raw).encode(encoding)
    data = replace(data, {"word/document.xml": raw})
    e = EditorSession(data)
    result = e.insert_text(" Текст 😀 ", expected_revision=0)
    root = ET.fromstring(parts(result.document.data)["word/document.xml"])
    assert root.find(".//{" + W + "}r/{" + W + "}rPr/{" + W + "}b") is not None
    assert result.document.projection.blocks[0].text == " Текст 😀 "


def test_local_run_rebinding_remains_valid_after_enter_and_typing():
    data = source(
        f'<p xmlns="{W}" xmlns:q="urn:unused"><r xmlns:q="{W}">'
        "<q:rPr><q:i/></q:rPr><q:t>Alpha</q:t></r></p>"
    )
    e = EditorSession(data)
    at(e, 5)
    entered = e.enter(expected_revision=0)
    result = e.insert_text("Next", expected_revision=1)
    right = ET.fromstring(parts(result.document.data)["word/document.xml"]).findall(
        "{" + W + "}body/{" + W + "}p"
    )[1]
    run = next(
        r
        for r in right
        if r.find("{" + W + "}t") is not None and r.find("{" + W + "}t").text == "Next"
    )
    assert run.find("{" + W + "}rPr/{" + W + "}i") is not None
    assert e.undo(expected_revision=2).document.data == entered.document.data


def test_typing_near_native_controls_keeps_every_original_control():
    data = source(
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>A</w:t><w:tab/></w:r>"
        "<w:r><w:rPr><w:i/></w:rPr><w:t>B</w:t><w:br/><w:t>C</w:t></w:r></w:p>"
    )
    old = "A\tB\nC"
    for offset in range(len(old) + 1):
        e = EditorSession(data)
        at(e, offset)
        result = e.insert_text("X", expected_revision=0)
        assert result.document.projection.blocks[0].text == old[:offset] + "X" + old[offset:]
        root = ET.fromstring(parts(result.document.data)["word/document.xml"])
        assert len(root.findall(".//{" + W + "}tab")) == len(root.findall(".//{" + W + "}br")) == 1


def test_protected_insertion_refuses_change_but_empty_input_is_noop():
    data = create_docx()
    settings = parts(data)["word/settings.xml"]
    data = replace(
        data,
        {
            "word/settings.xml": settings.replace(
                b"<w:compat>", b"<w:documentProtection/><w:compat>"
            )
        },
    )
    e = EditorSession(data)
    before = e.snapshot()
    assert e.insert_text("", expected_revision=0) == before
    with pytest.raises(BoundaryError):
        e.insert_text("X", expected_revision=0)
    assert e.snapshot() == before


def test_exact_insert_character_budget_is_accepted_without_truncation():
    e = EditorSession(create_docx())
    result = e.insert_text("x" * 100000, expected_revision=0)
    assert len(result.document.projection.blocks[0].text) == 100000
    assert result.selection.focus.offset == 100000


def test_typing_and_seed_are_inert_when_loaded_on_first_call():
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
e.insert_text('Alpha',expected_revision=0)
e.enter(expected_revision=1)
s=e.insert_text('Beta',expected_revision=2)
assert [p.text for p in s.document.projection.blocks]==['Alpha','Beta']
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
