"""Frozen D03-15B3: formatting-aware insertion and empty-paragraph typing seed."""

from xml.etree import ElementTree as ET

import pytest
from test_docx_boundaries import NS, W, parts, source

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.editor import (
    Caret,
    EditorError,
    EditorSelection,
    EditorSession,
    EditorSnapshot,
)
from ara.docx_package.session import SessionError, SessionLimits


def at(editor, index=0, offset=0, affinity="right"):
    s = editor.snapshot()
    p = s.document.projection.blocks[index]
    c = Caret(p.anchor, offset, affinity)
    return editor.capture(EditorSelection(c, c), expected_revision=s.document.revision)


@pytest.mark.parametrize(
    "initial,offset,value",
    [
        ("", 0, "First"),
        ("Alpha", 0, " "),
        ("Alpha", 2, " 😀 & <x> е\u0301 "),
        ("Alpha", 5, " end"),
    ],
)
def test_single_paragraph_insertion_is_exact_and_reversible(initial, offset, value):
    data = create_docx((NewParagraph(initial),))
    e = EditorSession(data)
    before = at(e, offset=offset)
    changed = e.insert_text(value, expected_revision=0)
    assert changed.document.projection.blocks[0].text == initial[:offset] + value + initial[offset:]
    assert (
        changed.selection.focus.offset == offset + len(value)
        and changed.selection.focus.affinity == "left"
    )
    assert changed.document.undo_depth == 1 and changed.position_id == 1
    restored = e.undo(expected_revision=1)
    assert restored.document.data == data and restored.selection == before.selection
    assert e.redo(expected_revision=2).document.data == changed.document.data


@pytest.mark.parametrize(
    "markup", ["<w:p/>", "<w:p><w:pPr/></w:p>", "<w:p><w:pPr><w:rPr><w:b/></w:rPr></w:pPr></w:p>"]
)
def test_typing_without_a_text_span_or_run(markup):
    data = source(markup)
    e = EditorSession(data)
    changed = e.insert_text("Typed", expected_revision=0)
    assert changed.document.projection.blocks[0].text == "Typed"
    root = ET.fromstring(parts(changed.document.data)["word/document.xml"])
    if "<w:b/>" in markup:
        assert root.find(".//w:r/w:rPr/w:b", NS) is not None


@pytest.mark.parametrize("affinity,bold", [("left", True), ("right", False)])
def test_run_affinity_preserves_each_original_character_format(affinity, bold):
    data = source(
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r>"
        "<w:r><w:rPr><w:i/></w:rPr><w:t>Italic</w:t></w:r></w:p>"
    )
    e = EditorSession(data)
    at(e, offset=4, affinity=affinity)
    result = e.insert_text("X", expected_revision=0)
    root = ET.fromstring(parts(result.document.data)["word/document.xml"])
    typed = next(
        r
        for r in root.findall(".//w:r", NS)
        if r.find("w:t", NS) is not None and r.find("w:t", NS).text == "X"
    )
    assert (typed.find("w:rPr/w:b", NS) is not None) == bold
    assert (typed.find("w:rPr/w:i", NS) is not None) == (not bold)
    again = e.insert_text("Y", expected_revision=1)
    assert again.document.projection.blocks[0].text == "BoldXYItalic"


def test_enter_retains_inline_typing_format_and_one_enter_undo_step():
    data = source(
        '<w:p><w:r><w:rPr><w:i/><w:color w:val="123456"/></w:rPr><w:t>Italic</w:t></w:r></w:p>'
    )
    # Use real AIRA styles for Enter's style policy, preserving the synthetic main.
    from test_docx_boundaries import replace

    template = create_docx((NewParagraph("Italic"),))
    data = replace(template, {"word/document.xml": parts(data)["word/document.xml"]})
    e = EditorSession(data)
    before = at(e, offset=6)
    entered = e.enter(expected_revision=0)
    assert entered.document.undo_depth == 1
    typed = e.insert_text("Continued", expected_revision=1)
    right = ET.fromstring(parts(typed.document.data)["word/document.xml"]).findall(
        "w:body/w:p", NS
    )[1]
    run = next(
        r
        for r in right.findall("w:r", NS)
        if r.find("w:t", NS) is not None and r.find("w:t", NS).text == "Continued"
    )
    assert run.find("w:rPr/w:i", NS) is not None
    assert run.find("w:rPr/w:color", NS).get("{" + W + "}val") == "123456"
    assert e.undo(expected_revision=2).document.data == entered.document.data
    undone = e.undo(expected_revision=3)
    assert undone.document.data == data and undone.selection == before.selection


def test_next_style_does_not_carry_heading_typing_overrides():
    data = create_docx((NewParagraph("Heading", "heading1"),))
    e = EditorSession(data)
    at(e, offset=7)
    e.enter(expected_revision=0)
    typed = e.insert_text("Body", expected_revision=1)
    blocks = typed.document.projection.blocks
    assert [p.style_id for p in blocks] == ["Heading1", "Normal"]
    right = ET.fromstring(parts(typed.document.data)["word/document.xml"]).findall(
        "w:body/w:p", NS
    )[1]
    assert right.find(".//w:rPr/w:b", NS) is None


def test_text_validation_noop_and_candidate_failure_preserve_all_history(monkeypatch):
    e = EditorSession(create_docx((NewParagraph("Alpha"),)))
    at(e, offset=2)
    e.insert_text("X", expected_revision=0)
    before = e.undo(expected_revision=1)
    assert e.insert_text("", expected_revision=2) == before
    for value in (None, True, "bad\x00", "bad\ud800", "a\nb", "a\tb", "a\rb"):
        with pytest.raises(EditorError) as caught:
            e.insert_text(value, expected_revision=2)
        assert caught.value.code == "invalid_input" and e.snapshot() == before
    with pytest.raises(EditorError) as caught:
        e.insert_text("x" * 100001, expected_revision=2)
    assert caught.value.code == "text_limit_exceeded"
    with pytest.raises(SessionError):
        e.insert_text("X", expected_revision=1)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic reply failure")

    with monkeypatch.context() as patch:
        patch.setattr(EditorSnapshot, "__init__", fail)
        with pytest.raises(RuntimeError):
            e.insert_text("X", expected_revision=2)
    assert e.snapshot() == before


def test_insert_obeys_current_history_byte_budget():
    data = create_docx()
    e = EditorSession(data, session_limits=SessionLimits(max_history_bytes=len(data)))
    before = e.snapshot()
    with pytest.raises(SessionError):
        e.insert_text("New content", expected_revision=0)
    assert e.snapshot() == before
