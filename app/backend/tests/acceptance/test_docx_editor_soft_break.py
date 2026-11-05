"""Frozen D03-15D: native soft break, formatting and exact selection history."""

from xml.etree import ElementTree as ET

import pytest
from test_docx_boundaries import NS, parts, source

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.editor import (
    Caret,
    EditorError,
    EditorSelection,
    EditorSession,
    EditorSnapshot,
)
from ara.docx_package.session import SessionError, SessionLimits


def select(e, lo, hi=None, affinity="right"):
    before = e.snapshot()
    p = before.document.projection.blocks[0]
    return e.capture(
        EditorSelection(
            Caret(p.anchor, lo, affinity), Caret(p.anchor, lo if hi is None else hi, affinity)
        ),
        expected_revision=before.document.revision,
    )


@pytest.mark.parametrize("text,offset", [("", 0), ("Alpha", 0), ("Alpha", 2), ("Alpha", 5)])
def test_soft_break_is_one_native_control_and_one_exact_undo_step(text, offset):
    data = create_docx((NewParagraph(text),))
    e = EditorSession(data)
    before = select(e, offset)
    changed = e.insert_soft_break(expected_revision=0)
    blocks = changed.document.projection.blocks
    assert len(blocks) == 1 and blocks[0].text == text[:offset] + "\n" + text[offset:]
    root = ET.fromstring(parts(changed.document.data)["word/document.xml"])
    assert len(root.findall(".//w:br", NS)) == 1
    assert all("\n" not in (t.text or "") for t in root.findall(".//w:t", NS))
    assert changed.selection.anchor == changed.selection.focus
    assert changed.selection.focus.offset == offset + 1
    assert changed.selection.focus.affinity == "left"
    assert changed.document.revision == 1 and changed.document.undo_depth == 1
    assert changed.position_id == 1
    restored = e.undo(expected_revision=1)
    assert restored.document.data == data and restored.selection == before.selection
    redone = e.redo(expected_revision=2)
    assert redone.document.data == changed.document.data
    assert redone.selection == changed.selection and redone.position_id == changed.position_id


@pytest.mark.parametrize("start,end", [(1, 4), (4, 1)])
def test_soft_break_replaces_forward_or_reverse_selection(start, end):
    e = EditorSession(create_docx((NewParagraph("Alpha"),)))
    before = select(e, start, end)
    changed = e.insert_soft_break(expected_revision=0)
    assert changed.document.projection.blocks[0].text == "A\na"
    assert changed.selection.focus.offset == 2
    assert e.undo(expected_revision=1).selection == before.selection


def test_control_selection_is_replaced_without_turning_breaks_into_paragraphs():
    e = EditorSession(
        source("<w:p><w:r><w:t>A</w:t><w:tab/><w:cr/><w:br/><w:t>B</w:t></w:r></w:p>")
    )
    select(e, 1, 4)
    changed = e.insert_soft_break(expected_revision=0)
    assert [p.text for p in changed.document.projection.blocks] == ["A\nB"]
    root = ET.fromstring(parts(changed.document.data)["word/document.xml"])
    assert len(root.findall(".//w:br", NS)) == 1
    assert not root.findall(".//w:tab", NS) and not root.findall(".//w:cr", NS)


@pytest.mark.parametrize("style", ["heading1", "numbered", "bullet"])
def test_soft_break_keeps_style_list_identity_and_paragraph_count(style):
    e = EditorSession(create_docx((NewParagraph("Alpha", style), NewParagraph("Untouched"))))
    before = select(e, 5)
    original = before.document.projection.blocks[0]
    changed = e.insert_soft_break(expected_revision=0)
    blocks = changed.document.projection.blocks
    assert len(blocks) == 2 and blocks[0].text == "Alpha\n" and blocks[1].text == "Untouched"
    assert (blocks[0].style_id, blocks[0].numbering_id, blocks[0].numbering_level) == (
        original.style_id,
        original.numbering_id,
        original.numbering_level,
    )
    old = ET.fromstring(parts(before.document.data)["word/document.xml"]).find("w:body/w:p", NS)
    new = ET.fromstring(parts(changed.document.data)["word/document.xml"]).find("w:body/w:p", NS)
    assert old.attrib == new.attrib
    assert ET.tostring(old.find("w:pPr", NS)) == ET.tostring(new.find("w:pPr", NS))


@pytest.mark.parametrize("affinity,bold", [("left", True), ("right", False)])
def test_break_and_following_typing_inherit_selected_run_affinity(affinity, bold):
    data = source(
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r>"
        "<w:r><w:rPr><w:i/></w:rPr><w:t>Italic</w:t></w:r></w:p>"
    )
    e = EditorSession(data)
    select(e, 4, affinity=affinity)
    changed = e.insert_soft_break(expected_revision=0)
    typed = e.insert_text("X", expected_revision=1)
    assert typed.document.projection.blocks[0].text == "Bold\nXItalic"
    for document, child in ((changed, "w:br"), (typed, "w:t")):
        runs = ET.fromstring(parts(document.document.data)["word/document.xml"]).findall(
            ".//w:r", NS
        )
        run = next(
            r
            for r in runs
            if r.find(child, NS) is not None and (child == "w:br" or r.find(child, NS).text == "X")
        )
        assert (run.find("w:rPr/w:b", NS) is not None) == bold
        assert (run.find("w:rPr/w:i", NS) is not None) == (not bold)
    root = ET.fromstring(parts(typed.document.data)["word/document.xml"])
    for original, tag in (("Bold", "w:b"), ("Italic", "w:i")):
        run = next(
            r
            for r in root.findall(".//w:r", NS)
            if r.find("w:t", NS) is not None and r.find("w:t", NS).text == original
        )
        assert run.find("w:rPr/" + tag, NS) is not None


def test_stale_multi_paragraph_and_reply_errors_leave_the_whole_state(monkeypatch):
    e = EditorSession(create_docx((NewParagraph("Alpha"), NewParagraph("Beta"))))
    before = e.snapshot()
    blocks = before.document.projection.blocks
    e.capture(
        EditorSelection(Caret(blocks[0].anchor, 1), Caret(blocks[1].anchor, 2)),
        expected_revision=0,
    )
    before = e.snapshot()
    with pytest.raises(SessionError):
        e.insert_soft_break(expected_revision=1)
    with pytest.raises(EditorError) as caught:
        e.insert_soft_break(expected_revision=0)
    assert caught.value.code == "unsupported_intent" and e.snapshot() == before
    select(e, 2)
    e.insert_text("X", expected_revision=0)
    before = e.undo(expected_revision=1)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic reply failure")

    with monkeypatch.context() as patch:
        patch.setattr(EditorSnapshot, "__init__", fail)
        with pytest.raises(RuntimeError):
            e.insert_soft_break(expected_revision=2)
    assert e.snapshot() == before and e.snapshot().document.redo_depth == 1


def test_history_budget_failure_preserves_selection_and_saved_mark():
    data = create_docx((NewParagraph("Alpha"),))
    e = EditorSession(data, session_limits=SessionLimits(max_history_bytes=len(data)))
    before = select(e, 2)
    with pytest.raises(SessionError):
        e.insert_soft_break(expected_revision=0)
    assert e.snapshot() == before and not e.snapshot().document.is_dirty
