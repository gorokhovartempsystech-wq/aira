"""Frozen D03-16A: exact working copy recovery without a fake saved state."""

from dataclasses import replace
from hashlib import sha256

import pytest

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.editor import (
    Caret,
    EditorError,
    EditorSelection,
    EditorSession,
    EditorSnapshot,
)
from ara.docx_package.projection import SourceAnchor
from ara.docx_package.session import DocxSession, SessionError, SessionLimits


def data():
    return create_docx((NewParagraph("A😀е\u0301"), NewParagraph(""), NewParagraph("Tail")))


def selection(raw, reverse=False):
    e = EditorSession(raw)
    blocks = e.snapshot().document.projection.blocks
    points = [Caret(blocks[0].anchor, 2, "left"), Caret(blocks[2].anchor, 3, "right")]
    if reverse:
        points.reverse()
    selected = EditorSelection(*points)
    # Confirm fixtures are valid through the existing strict selection path before freeze.
    assert e.capture(selected, expected_revision=0).selection == selected
    return selected


def saved():
    return sha256(create_docx((NewParagraph("Saved base"),))).hexdigest()


@pytest.mark.parametrize("same", [False, True])
def test_core_restores_dirty_and_exact_package_without_undo_history(same):
    raw = data()
    digest = sha256(raw).hexdigest() if same else saved()
    core = DocxSession.restore(raw, saved_sha256=digest)
    s = core.snapshot()
    assert s.data == raw and s.is_dirty == (not same)
    assert s.revision == 0 and s.undo_depth == 0 and s.redo_depth == 0
    assert s.projection.source.sha256 == sha256(raw).hexdigest()
    with pytest.raises(SessionError) as caught:
        core.undo(expected_revision=0)
    assert caught.value.code == "nothing_to_undo"
    assert not DocxSession(raw).snapshot().is_dirty


@pytest.mark.parametrize("reverse", [False, True])
def test_editor_restores_selection_direction_affinity_and_code_point_offsets(reverse):
    raw = data()
    selected = selection(raw, reverse)
    e = EditorSession.restore(raw, saved_sha256=saved(), selection=selected)
    s = e.snapshot()
    assert s.selection == selected and s.document.data == raw and s.document.is_dirty
    assert s.position_id == 0 and s.document.revision == 0
    assert s.document.undo_depth == s.document.redo_depth == 0
    b = s.document.projection.blocks[1]
    caret = Caret(b.anchor, 0, "left")
    assert e.capture(EditorSelection(caret, caret), expected_revision=0).selection.focus == caret


def test_restored_dirty_typing_enter_paste_undo_and_redo_return_working_copy():
    raw = data()
    selected = selection(raw)
    e = EditorSession.restore(raw, saved_sha256=saved(), selection=selected)
    c = selected.anchor
    initial = e.capture(EditorSelection(c, c), expected_revision=0)
    one = e.insert_text("Typed", expected_revision=0)
    two = e.enter(expected_revision=1)
    three = e.paste_text("First\nSecond", expected_revision=2)
    assert (one.position_id, two.position_id, three.position_id) == (1, 2, 3)
    assert e.undo(expected_revision=3).document.data == two.document.data
    assert e.undo(expected_revision=4).document.data == one.document.data
    restored = e.undo(expected_revision=5)
    assert restored.document.data == raw and restored.selection == initial.selection
    assert restored.position_id == 0 and restored.document.is_dirty
    with pytest.raises(SessionError):
        e.undo(expected_revision=6)
    e.redo(expected_revision=6)
    e.redo(expected_revision=7)
    assert e.redo(expected_revision=8).document.data == three.document.data


def test_mark_saved_stays_revision_bound_and_preserves_recovered_history():
    raw = data()
    selected = selection(raw)
    e = EditorSession.restore(raw, saved_sha256=saved(), selection=selected)
    e.capture(EditorSelection(selected.anchor, selected.anchor), expected_revision=0)
    typed = e.insert_text("X", expected_revision=0)
    marked = e.mark_saved(expected_revision=1)
    assert not marked.document.is_dirty and marked.document.undo_depth == 1
    with pytest.raises(SessionError) as caught:
        e.mark_saved(expected_revision=0)
    assert caught.value.code == "stale_revision" and e.snapshot() == marked
    assert e.undo(expected_revision=1).document.is_dirty
    again = e.redo(expected_revision=2)
    assert again.document.data == typed.document.data and not again.document.is_dirty


class StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "digest",
    [None, True, b"0" * 64, StringSubclass("0" * 64), "0" * 63, "g" * 64, "A" * 64, " 0" * 32],
)
def test_digest_is_strict_for_both_factories(digest):
    raw = data()
    for cls, kwargs in ((DocxSession, {}), (EditorSession, {"selection": selection(raw)})):
        with pytest.raises(SessionError) as caught:
            cls.restore(raw, saved_sha256=digest, **kwargs)
        assert caught.value.code == "invalid_input"


@pytest.mark.parametrize("bad", ["source", "part", "path", "offset", "mutated"])
def test_invalid_selection_is_rejected_without_changing_caller(bad):
    raw = data()
    selected = selection(raw)
    anchor = selected.anchor.anchor
    if bad == "source":
        anchor = replace(anchor, source_sha256="0" * 64)
    if bad == "part":
        anchor = replace(anchor, part_name="word/elsewhere.xml")
    if bad == "path":
        anchor = replace(anchor, path=(999,))
    point = Caret(anchor, 999 if bad == "offset" else selected.anchor.offset)
    if bad == "mutated":
        object.__setattr__(point, "offset", -1)
    # Construct a deliberately bypassed DTO for invalid-input revalidation.
    supplied = object.__new__(EditorSelection)
    object.__setattr__(supplied, "anchor", point)
    object.__setattr__(supplied, "focus", point)
    with pytest.raises(EditorError) as caught:
        EditorSession.restore(raw, saved_sha256=saved(), selection=supplied)
    expected = (
        "stale_selection"
        if bad == "source"
        else ("invalid_input" if bad == "mutated" else "invalid_selection")
    )
    assert caught.value.code == expected
    assert selected == selection(raw)


def test_restored_state_does_not_alias_caller_or_returned_snapshots():
    raw = data()
    selected = selection(raw)
    limit = SessionLimits()
    e = EditorSession.restore(raw, saved_sha256=saved(), selection=selected, session_limits=limit)
    before = e.snapshot()
    object.__setattr__(selected.anchor.anchor, "path", (999,))
    object.__setattr__(selected.focus, "offset", 999)
    object.__setattr__(limit, "max_history_bytes", 1)
    assert e.snapshot() == before
    object.__setattr__(before.selection.anchor.anchor, "part_name", "word/elsewhere.xml")
    object.__setattr__(before.document.projection.blocks[0].anchor, "source_sha256", "0" * 64)
    fresh = e.snapshot()
    assert fresh.selection == selection(raw)
    assert fresh.document.projection.source.sha256 == sha256(raw).hexdigest()


def test_restore_budget_and_reply_failure_do_not_touch_a_live_session(monkeypatch):
    raw = data()
    live = EditorSession(raw)
    before = live.snapshot()
    with pytest.raises(SessionError):
        EditorSession.restore(
            raw,
            saved_sha256=saved(),
            selection=selection(raw),
            session_limits=SessionLimits(max_history_bytes=len(raw) - 1),
        )
    selected = selection(raw)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic response failure")

    with monkeypatch.context() as patch:
        patch.setattr(EditorSnapshot, "__init__", fail)
        with pytest.raises(RuntimeError):
            EditorSession.restore(raw, saved_sha256=saved(), selection=selected)
    assert live.snapshot() == before
    assert selected == selection(raw)


def test_restore_does_not_treat_unrelated_anchor_as_a_valid_source():
    raw = data()
    a = SourceAnchor("a" * 64, "word/document.xml", (0, 0))
    c = Caret(a, 0)
    with pytest.raises(EditorError) as caught:
        EditorSession.restore(raw, saved_sha256=saved(), selection=EditorSelection(c, c))
    assert caught.value.code == "stale_selection"
