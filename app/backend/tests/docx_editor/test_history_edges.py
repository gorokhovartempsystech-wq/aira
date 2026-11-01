"""Controller rollback, range selection, opaque targets and metadata budgets."""

import pytest

from ara.docx_package.boundaries import SplitParagraph
from ara.docx_package.editor import (
    Caret,
    CaretTarget,
    EditorError,
    EditorSelection,
    EditorSession,
    EditorSnapshot,
    SelectionTarget,
)
from ara.docx_package.ranges import RangeEdit, TextPosition
from ara.docx_package.session import SessionError, SessionLimits
from tests.acceptance.test_docx_boundaries import p, source


def after(index=0, offset=0):
    point = CaretTarget(index, offset)
    return SelectionTarget(point, point)


def test_range_change_undo_and_stale_capture_cannot_overwrite_current():
    editor = EditorSession(source(p("Alpha") + p("Beta")))
    before = editor.snapshot()
    span = before.document.projection.blocks[0].spans[0]
    changed = editor.apply(
        (RangeEdit(TextPosition(span.anchor, 0), TextPosition(span.anchor, 5), "Alpha", "X"),),
        after=after(0, 1),
        expected_revision=0,
    )
    assert changed.selection.focus.offset == 1
    assert changed.selection.focus.anchor == changed.document.projection.blocks[0].anchor
    with pytest.raises(EditorError) as caught:
        editor.capture(before.selection, expected_revision=1)
    assert caught.value.code == "stale_selection"
    assert editor.snapshot() == changed
    assert editor.undo(expected_revision=1).selection == before.selection


@pytest.mark.parametrize("operation", ["capture", "undo", "redo", "mark_saved"])
def test_controller_reply_allocation_failure_preserves_all_state(operation, monkeypatch):
    editor = EditorSession(source(p("Alpha")))
    p0 = editor.snapshot().document.projection.blocks[0]
    changed = editor.apply_boundary(SplitParagraph(p0.anchor, p0.text, 2), expected_revision=0)
    if operation == "redo":
        before = editor.undo(expected_revision=1)
    else:
        before = changed

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic allocation failure")

    with monkeypatch.context() as patch:
        patch.setattr(EditorSnapshot, "__init__", fail)
        with pytest.raises(RuntimeError):
            if operation == "capture":
                editor.capture(before.selection, expected_revision=before.document.revision)
            else:
                getattr(editor, operation)(expected_revision=before.document.revision)
    assert editor.snapshot() == before


def test_strict_models_bad_anchor_and_missing_after_revision_priority():
    editor = EditorSession(source(p("Alpha")))
    s = editor.snapshot()
    a = s.selection.focus.anchor
    for value in (True, -1, 1.0):
        with pytest.raises(EditorError):
            Caret(a, value)
        with pytest.raises(EditorError):
            CaretTarget(value, 0)
    with pytest.raises(EditorError):
        Caret(a, 0, "middle")
    span = s.document.projection.blocks[0].spans[0]
    with pytest.raises(EditorError) as caught:
        editor.capture(
            EditorSelection(Caret(span.anchor, 0), Caret(span.anchor, 0)), expected_revision=0
        )
    assert caught.value.code == "invalid_selection"
    for method in (editor.apply, editor.apply_structure):
        with pytest.raises(SessionError):
            method((), after=None, expected_revision=1)
    assert editor.snapshot() == s


def test_state_budget_eviction_and_table_target_do_not_desynchronize_metadata():
    data = source(p("Alpha"))
    editor = EditorSession(data, session_limits=SessionLimits(max_history_states=1))
    p0 = editor.snapshot().document.projection.blocks[0]
    changed = editor.apply_boundary(SplitParagraph(p0.anchor, p0.text, 2), expected_revision=0)
    assert changed.position_id == 1 and changed.document.undo_depth == 0
    with pytest.raises(SessionError):
        editor.undo(expected_revision=1)
    assert editor.snapshot() == changed
    data = source(p("Alpha") + "<w:tbl><w:tr><w:tc>" + p("Cell") + "</w:tc></w:tr></w:tbl>")
    editor = EditorSession(data)
    s = editor.snapshot()
    with pytest.raises(EditorError) as caught:
        editor.apply_formats((), after=after(1), expected_revision=0)
    assert caught.value.code == "invalid_selection" and editor.snapshot() == s
