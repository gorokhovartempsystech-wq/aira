"""Frozen D03-15B1: exact history with isolated, source-relative selections."""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from ara.docx_package.boundaries import JoinParagraphs, SplitParagraph
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.formatting import ParagraphFormat
from ara.docx_package.projection import SourceAnchor
from ara.docx_package.session import SessionError, SessionLimits
from ara.docx_package.structure import InsertParagraph


def api():
    return importlib.import_module("ara.docx_package.editor")


def raw():
    return create_docx((NewParagraph("Alpha 😀"), NewParagraph("Beta")))


def selection(state, index=0, offset=0, affinity="right"):
    p = state.document.projection.blocks[index]
    caret = api().Caret(p.anchor, offset, affinity)
    return api().EditorSelection(caret, caret)


def target(index=0, offset=0, affinity="right"):
    caret = api().CaretTarget(index, offset, affinity)
    return api().SelectionTarget(caret, caret)


def test_split_join_undo_redo_restore_exact_data_and_caret():
    editor = api().EditorSession(raw())
    initial = editor.snapshot()
    before = editor.capture(selection(initial, offset=3, affinity="left"), expected_revision=0)
    p = before.document.projection.blocks[0]
    split = editor.apply_boundary(SplitParagraph(p.anchor, p.text, 3), expected_revision=0)
    assert split.position_id == 1
    assert split.selection.focus.anchor == split.document.projection.blocks[1].anchor
    assert split.selection.focus.offset == 0
    undone = editor.undo(expected_revision=1)
    assert undone.document.data == initial.document.data and undone.selection == before.selection
    assert undone.position_id == 0 and undone.document.revision == 2
    redone = editor.redo(expected_revision=2)
    assert redone.document.data == split.document.data and redone.selection == split.selection
    a, b = redone.document.projection.blocks[:2]
    joined = editor.apply_boundary(
        JoinParagraphs(a.anchor, b.anchor, a.text, b.text), expected_revision=3
    )
    assert joined.position_id == 2 and joined.selection.focus.offset == 3
    assert joined.selection.focus.anchor == joined.document.projection.blocks[0].anchor
    assert editor.undo(expected_revision=4).document.data == split.document.data


def test_reverse_selection_save_and_format_history():
    editor = api().EditorSession(raw())
    initial = editor.snapshot()
    reverse = api().EditorSelection(
        selection(initial, 1, 2).focus, selection(initial, 0, 1, "left").focus
    )
    captured = editor.capture(reverse, expected_revision=0)
    assert captured.document.revision == 0 and captured.position_id == 0
    p = captured.document.projection.blocks[0]
    changed = editor.apply_formats(
        (ParagraphFormat(p.anchor, p.text, "Heading1"),), expected_revision=0
    )
    assert changed.selection.anchor.offset == 2 and changed.selection.focus.offset == 1
    assert changed.selection.focus.affinity == "left"
    saved = editor.mark_saved(expected_revision=1)
    assert not saved.document.is_dirty and saved.selection == changed.selection
    undone = editor.undo(expected_revision=1)
    assert undone.selection == reverse and undone.document.is_dirty
    assert not editor.redo(expected_revision=2).document.is_dirty


def test_invalid_after_and_reply_failure_do_not_publish_candidate(monkeypatch):
    editor = api().EditorSession(raw())
    before = editor.snapshot()
    p = before.document.projection.blocks[0]
    command = (InsertParagraph(p.anchor, p.text, ("New",)),)
    with pytest.raises(api().EditorError) as caught:
        editor.apply_structure(command, after=target(99), expected_revision=0)
    assert caught.value.code == "invalid_selection"
    assert editor.snapshot() == before

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic reply failure")

    with monkeypatch.context() as patch:
        patch.setattr(api().EditorSnapshot, "__init__", fail)
        with pytest.raises(RuntimeError):
            editor.apply_structure(command, after=target(1, 1), expected_revision=0)
    assert editor.snapshot() == before
    changed = editor.apply_structure(command, after=target(1, 1), expected_revision=0)
    assert changed.position_id == 1 and changed.document.undo_depth == 1
    assert editor.undo(expected_revision=1).selection == before.selection


def test_redo_noop_branch_and_metadata_eviction():
    editor = api().EditorSession(raw(), session_limits=SessionLimits(max_history_states=2))
    first = editor.snapshot()
    p = first.document.projection.blocks[0]
    divided = editor.apply_boundary(SplitParagraph(p.anchor, p.text, 2), expected_revision=0)
    restored = editor.undo(expected_revision=1)
    assert editor.apply_formats((), expected_revision=2) == restored
    assert editor.redo(expected_revision=2).position_id == divided.position_id
    restored = editor.undo(expected_revision=3)
    p = restored.document.projection.blocks[0]
    branch = editor.apply_formats(
        (ParagraphFormat(p.anchor, p.text, "Heading1"),), expected_revision=4
    )
    assert branch.position_id == 2 and branch.document.redo_depth == 0
    p = branch.document.projection.blocks[0]
    latest = editor.apply_structure(
        (InsertParagraph(p.anchor, p.text, ("Last",)),), after=target(1), expected_revision=5
    )
    assert latest.position_id == 3 and latest.document.undo_depth == 1
    old = editor.undo(expected_revision=6)
    assert old.position_id == 2 and old.selection == branch.selection
    assert old.document.undo_depth == 0
    with pytest.raises(SessionError):
        editor.undo(expected_revision=7)


def test_frozen_snapshot_poisoning_and_strict_stale_guards():
    editor = api().EditorSession(raw())
    other = api().EditorSession(raw())
    first = editor.snapshot()
    object.__setattr__(first.selection.focus.anchor, "source_sha256", "0" * 64)
    object.__setattr__(first.selection.anchor, "offset", 999)
    assert editor.snapshot() == other.snapshot()
    before = editor.snapshot()
    p = before.document.projection.blocks[0]
    invalid = api().EditorSelection(
        api().Caret(SourceAnchor("0" * 64, p.anchor.part_name, p.anchor.path), 0),
        api().Caret(p.anchor, 0),
    )
    with pytest.raises(api().EditorError) as caught:
        editor.capture(invalid, expected_revision=0)
    assert caught.value.code == "stale_selection"
    for revision in (True, -1, 1):
        with pytest.raises(SessionError):
            editor.capture(before.selection, expected_revision=revision)
    bad = selection(before)
    object.__setattr__(bad.focus, "offset", True)
    with pytest.raises(api().EditorError):
        editor.capture(bad, expected_revision=0)
    assert editor.snapshot() == before


def test_explicit_after_tracks_structure_and_noop_cursor_without_new_id():
    editor = api().EditorSession(raw())
    s = editor.snapshot()
    p = s.document.projection.blocks[0]
    s = editor.apply_structure(
        (InsertParagraph(p.anchor, p.text, ("New",)),),
        after=target(1, 2, "left"),
        expected_revision=0,
    )
    assert s.selection.focus.anchor == s.document.projection.blocks[1].anchor
    assert s.selection.focus.offset == 2 and s.selection.focus.affinity == "left"
    moved = editor.apply_formats((), after=target(2, 1), expected_revision=1)
    assert moved.position_id == s.position_id and moved.document == s.document
    assert moved.selection.focus.anchor == moved.document.projection.blocks[2].anchor
    restored = editor.undo(expected_revision=1)
    assert restored.position_id == 0
    assert editor.redo(expected_revision=2).selection == moved.selection


def test_modules_and_controller_are_inert():
    script = """
import importlib,builtins,io,os,socket,subprocess,logging
from pathlib import Path
from ara.docx_package.creation import create_docx
from ara.docx_package.boundaries import SplitParagraph
raw=create_docx()
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes')):
    setattr(obj,name,forbidden)
m=importlib.import_module('ara.docx_package.editor');e=m.EditorSession(raw)
p=e.snapshot().document.projection.blocks[0]
s=e.apply_boundary(SplitParagraph(p.anchor,p.text,0),expected_revision=0)
assert s.selection.focus.anchor==s.document.projection.blocks[1].anchor
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
