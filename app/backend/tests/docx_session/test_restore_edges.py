"""Recovery limits, rich package identity and first-call inertness."""

import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.boundaries import SplitParagraph
from ara.docx_package.editor import Caret, EditorError, EditorSelection, EditorSession
from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.projection import ProjectionError, ProjectionLimits
from ara.docx_package.session import DocxSession, SessionError, SessionLimits
from tests.acceptance.test_docx_boundaries import p, parts, source


def restore(raw, **kwargs):
    s = EditorSession(raw).snapshot()
    c = Caret(s.document.projection.blocks[0].anchor, 0)
    return EditorSession.restore(
        raw, saved_sha256="0" * 64, selection=EditorSelection(c, c), **kwargs
    )


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"limits": DocxLimits(max_archive_bytes=1)}, DocxError),
        ({"projection_limits": ProjectionLimits(max_nodes=1)}, ProjectionError),
        ({"session_limits": SessionLimits(max_history_bytes=1)}, SessionError),
        ({"limits": True}, DocxError),
        ({"projection_limits": True}, ProjectionError),
    ],
)
def test_restore_keeps_constructor_budgets_and_errors(kwargs, error):
    raw = source(p("Alpha"))
    with pytest.raises(error):
        restore(raw, **kwargs)


def test_mutated_limits_and_nonbyte_package_are_not_trusted():
    raw = source(p("Alpha"))
    limit = SessionLimits()
    object.__setattr__(limit, "max_history_states", True)
    with pytest.raises(SessionError):
        restore(raw, session_limits=limit)
    for value in (None, bytearray(raw), "SYNTHETIC_PRIVATE", b"bad package"):
        with pytest.raises(DocxError) as caught:
            DocxSession.restore(value, saved_sha256="0" * 64)
        assert "SYNTHETIC_PRIVATE" not in repr(caught.value)


def test_cannot_restore_to_an_opaque_block_or_create_an_editable_paragraph():
    raw = source('<w:altChunk xmlns:r="urn:unused"/>' + p("Alpha"))
    s = EditorSession(raw).snapshot()
    opaque = s.document.projection.blocks[0]
    c = Caret(opaque.anchor, 0)
    with pytest.raises(EditorError) as caught:
        EditorSession.restore(raw, saved_sha256="0" * 64, selection=EditorSelection(c, c))
    assert caught.value.code == "invalid_selection"


def test_rich_restore_exact_format_edit_undo_and_no_fake_history():
    raw = Path("tests/fixtures/docx/rich-source.docx").read_bytes()
    original = EditorSession(raw).snapshot()
    index = next(
        i
        for i, p in enumerate(original.document.projection.blocks)
        if p.kind == "paragraph" and p.text == "Device classification"
    )
    c = Caret(original.document.projection.blocks[index].anchor, 6, "left")
    selection = EditorSelection(c, c)
    e = EditorSession.restore(raw, saved_sha256="0" * 64, selection=selection)
    assert sha256(e.snapshot().document.data).digest() == sha256(raw).digest()
    p = e.snapshot().document.projection.blocks[index]
    split = e.apply_boundary(SplitParagraph(p.anchor, p.text, 6), expected_revision=0)
    right = split.document.projection.blocks[index + 1]
    changed = e.apply_formats(
        (ParagraphFormat(right.anchor, right.text, style_id="Heading2"),), expected_revision=1
    )
    assert changed.document.undo_depth == 2
    assert all(
        parts(raw)[n] == parts(changed.document.data)[n]
        for n in parts(raw)
        if n != "word/document.xml"
    )
    e.undo(expected_revision=2)
    restored = e.undo(expected_revision=3)
    assert restored.document.data == raw and restored.selection == selection
    assert restored.document.is_dirty and restored.document.undo_depth == 0


def test_mutated_nested_anchor_and_core_response_failure_do_not_leak_partial_object(monkeypatch):
    raw = source(p("Alpha"))
    e = restore(raw)
    selected = e.snapshot().selection
    bad = replace(selected.anchor.anchor)
    object.__setattr__(bad, "path", (True,))
    c = object.__new__(Caret)
    object.__setattr__(c, "anchor", bad)
    object.__setattr__(c, "offset", 0)
    object.__setattr__(c, "affinity", "right")
    selection = object.__new__(EditorSelection)
    object.__setattr__(selection, "anchor", c)
    object.__setattr__(selection, "focus", c)
    with pytest.raises(EditorError):
        EditorSession.restore(raw, saved_sha256="0" * 64, selection=selection)
    before = e.snapshot()

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic core snapshot failure")

    with monkeypatch.context() as patch:
        patch.setattr(DocxSession, "_snapshot", fail)
        with pytest.raises(RuntimeError):
            DocxSession.restore(raw, saved_sha256="0" * 64)
    assert e.snapshot() == before


def test_fresh_import_and_restore_are_inert():
    # Preload stdlib dependencies, then forbid side effects before importing application code.
    script = """
import builtins,io,os,socket,subprocess,logging,zipfile,xml.etree.ElementTree
import dataclasses,hashlib,typing
from pathlib import Path
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes')):
    setattr(obj,name,forbidden)
from ara.docx_package.creation import create_docx
from ara.docx_package.editor import EditorSession
from ara.docx_package.session import DocxSession
data=create_docx()
selection=EditorSession(data).snapshot().selection
e=EditorSession.restore(data,saved_sha256='0'*64,selection=selection)
assert e.snapshot().document.is_dirty
core=DocxSession.restore(data,saved_sha256=hashlib.sha256(data).hexdigest())
assert core.snapshot().is_dirty is False
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
