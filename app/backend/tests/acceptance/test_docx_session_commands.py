"""Frozen D03-15A: one exact history shared by all pure DOCX commands."""

import subprocess
import sys
from pathlib import Path

import pytest

from ara.docx_package.boundaries import (
    BoundaryError,
    BoundaryLimits,
    SplitParagraph,
    export_boundary,
)
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.formatting import (
    FormatLimits,
    FormattingError,
    ParagraphFormat,
    export_formats,
)
from ara.docx_package.ranges import RangeEdit, TextPosition
from ara.docx_package.session import DocxSession, SessionError, SessionLimits
from ara.docx_package.structure import (
    InsertParagraph,
    StructureError,
    StructureLimits,
    export_structure,
)


def raw():
    return create_docx((NewParagraph("Alpha"), NewParagraph("Beta"), NewParagraph("Gamma")))


def action(session, kind):
    state = session.snapshot()
    p = state.projection.blocks[0]
    if kind == "boundary":
        return session.apply_boundary, SplitParagraph(p.anchor, p.text, 2), export_boundary
    if kind == "structure":
        return (
            session.apply_structure,
            (InsertParagraph(p.anchor, p.text, ("New",)),),
            export_structure,
        )
    return session.apply_formats, (ParagraphFormat(p.anchor, p.text, "Heading1"),), export_formats


@pytest.mark.parametrize("kind", ["boundary", "structure", "format"])
def test_each_method_is_one_exact_history_step(kind):
    data = raw()
    session = DocxSession(data)
    method, command, export = action(session, kind)
    expected = export(data, command)
    result = method(command, expected_revision=0)
    assert result.data == expected
    assert (result.revision, result.undo_depth, result.redo_depth, result.is_dirty) == (
        1,
        1,
        0,
        True,
    )
    saved = session.mark_saved(expected_revision=1)
    assert not saved.is_dirty and saved.undo_depth == 1
    old = session.undo(expected_revision=1)
    assert old.data == data and old.revision == 2 and old.is_dirty
    again = session.redo(expected_revision=2)
    assert again.data == expected and again.revision == 3 and not again.is_dirty
    with pytest.raises(SessionError) as caught:
        method(command, expected_revision=1)
    assert caught.value.code == "stale_revision"
    assert session.snapshot() == again


def test_mixed_range_structure_format_history_restores_all_states():
    session = DocxSession(raw())
    states = [session.snapshot().data]
    span = session.snapshot().projection.blocks[0].spans[0]
    position = TextPosition(span.anchor, 0)
    result = session.apply(
        (RangeEdit(position, TextPosition(span.anchor, 1), "A", "Z"),), expected_revision=0
    )
    states.append(result.data)
    for kind in ("boundary", "structure", "format"):
        method, command, export = action(session, kind)
        result = method(command, expected_revision=result.revision)
        states.append(result.data)
    assert result.undo_depth == 4
    revision = result.revision
    for expected in reversed(states[:-1]):
        result = session.undo(expected_revision=revision)
        revision += 1
        assert result.data == expected and result.revision == revision
    for expected in states[1:]:
        result = session.redo(expected_revision=revision)
        revision += 1
        assert result.data == expected and result.revision == revision


def test_noop_and_errors_keep_redo_branch_while_actual_change_clears_it():
    session = DocxSession(raw())
    method, command, _ = action(session, "boundary")
    changed = method(command, expected_revision=0)
    before = session.undo(expected_revision=1)
    assert session.apply_structure((), expected_revision=2) == before
    assert session.apply_formats((), expected_revision=2) == before
    p = before.projection.blocks[0]
    assert (
        session.apply_formats((ParagraphFormat(p.anchor, p.text, "Normal"),), expected_revision=2)
        == before
    )
    for method, value, error in (
        (session.apply_boundary, SplitParagraph(p.anchor, "wrong", 1), BoundaryError),
        (session.apply_structure, (object(),), StructureError),
        (session.apply_formats, (ParagraphFormat(p.anchor, p.text, "Missing"),), FormattingError),
    ):
        with pytest.raises(error):
            method(value, expected_revision=2)
        assert session.snapshot() == before
    assert session.redo(expected_revision=2).data == changed.data
    before = session.undo(expected_revision=3)
    method, command, _ = action(session, "format")
    result = method(command, expected_revision=before.revision)
    assert result.redo_depth == 0
    with pytest.raises(SessionError) as caught:
        session.redo(expected_revision=result.revision)
    assert caught.value.code == "nothing_to_redo"


@pytest.mark.parametrize("kind", ["boundary", "structure", "format"])
def test_limits_revision_validation_and_reply_failure_are_atomic(kind, monkeypatch):
    session = DocxSession(raw())
    method, command, _ = action(session, kind)
    before = session.snapshot()
    for revision, code in ((True, "invalid_input"), (-1, "invalid_input"), (1, "stale_revision")):
        with pytest.raises(SessionError) as caught:
            method(command, expected_revision=revision)
        assert caught.value.code == code
        assert session.snapshot() == before
    snapshot_type = type(before)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic reply fault")

    with monkeypatch.context() as patch:
        patch.setattr(snapshot_type, "__init__", fail)
        with pytest.raises(RuntimeError):
            method(command, expected_revision=0)
    assert session.snapshot() == before
    if kind == "boundary":
        kwargs = {"boundary_limits": BoundaryLimits(1)}
        error = BoundaryError
    elif kind == "structure":
        p = before.projection.blocks[0]
        command = (InsertParagraph(p.anchor, p.text, ("One", "Two")),)
        kwargs = {"structure_limits": StructureLimits(max_new_paragraphs=1)}
        error = StructureError
    else:
        p = before.projection.blocks[1]
        command += (ParagraphFormat(p.anchor, p.text, "Heading2"),)
        kwargs = {"format_limits": FormatLimits(max_formats=1)}
        error = FormattingError
    with pytest.raises(error):
        method(command, expected_revision=0, **kwargs)
    assert session.snapshot() == before


@pytest.mark.parametrize("kind", ["boundary", "structure", "format"])
def test_history_limits_evict_old_positions_across_new_methods(kind):
    session = DocxSession(raw(), session_limits=SessionLimits(max_history_states=1))
    method, command, _ = action(session, kind)
    result = method(command, expected_revision=0)
    assert result.undo_depth == result.redo_depth == 0
    with pytest.raises(SessionError) as caught:
        session.undo(expected_revision=1)
    assert caught.value.code == "nothing_to_undo"
    budget = len(raw())
    session = DocxSession(raw(), session_limits=SessionLimits(max_history_bytes=budget))
    method, command, export = action(session, kind)
    expected = export(raw(), command)
    assert len(expected) > budget
    before = session.snapshot()
    with pytest.raises(SessionError) as caught:
        method(command, expected_revision=0)
    assert caught.value.code == "session_limit_exceeded"
    assert session.snapshot() == before


def test_import_and_session_commands_are_inert():
    script = """
import builtins,io,os,socket,subprocess,logging,importlib
from pathlib import Path
from ara.docx_package.creation import create_docx,NewParagraph
from ara.docx_package.boundaries import SplitParagraph
from ara.docx_package.structure import InsertParagraph
from ara.docx_package.formatting import ParagraphFormat
raw=create_docx((NewParagraph('Original'),))
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes')):
    setattr(obj,name,forbidden)
session=importlib.import_module('ara.docx_package.session').DocxSession(raw)
p=session.snapshot().projection.blocks[0]
s=session.apply_boundary(SplitParagraph(p.anchor,p.text,3),expected_revision=0)
p=s.projection.blocks[0]
s=session.apply_structure((InsertParagraph(p.anchor,p.text,('Added',)),),expected_revision=1)
p=s.projection.blocks[0]
s=session.apply_formats((ParagraphFormat(p.anchor,p.text,'Heading1'),),expected_revision=2)
for r in (3,4,5):s=session.undo(expected_revision=r)
assert s.data==raw
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
