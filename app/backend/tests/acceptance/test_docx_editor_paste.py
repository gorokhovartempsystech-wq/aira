"""Frozen D03-15C plain paste boundaries, selection replacement and history."""

import importlib
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
from ara.docx_package.session import SessionError


def select(editor, start, end=None, index=0):
    s = editor.snapshot()
    p = s.document.projection.blocks[index]
    return editor.capture(
        EditorSelection(Caret(p.anchor, start), Caret(p.anchor, start if end is None else end)),
        expected_revision=s.document.revision,
    )


@pytest.mark.parametrize(
    "offset,value,expected",
    [
        (0, "X\nY", ["X", "YAlpha"]),
        (2, "X\nY", ["AlX", "Ypha"]),
        (5, "X\nY", ["AlphaX", "Y"]),
        (2, "\n", ["Al", "pha"]),
        (2, "\n\n", ["Al", "", "pha"]),
        (0, "\r\nX\rY\n", ["", "X", "Y", "Alpha"]),
        (2, "A\tB", ["AlA\tBpha"]),
    ],
)
def test_paste_preserves_boundaries_tabs_and_single_undo(offset, value, expected):
    data = create_docx((NewParagraph("Alpha"),))
    e = EditorSession(data)
    before = select(e, offset)
    changed = e.paste_text(value, expected_revision=0)
    assert [p.text for p in changed.document.projection.blocks] == expected
    assert (
        changed.document.undo_depth == 1
        and changed.position_id == 1
        and changed.document.revision == 1
    )
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    expected_offset = len(normalized.split("\n")[-1]) + (offset if "\n" not in normalized else 0)
    assert (
        changed.selection.focus.offset == expected_offset
        and changed.selection.focus.affinity == "left"
    )
    if "\t" in value:
        assert (
            len(
                ET.fromstring(parts(changed.document.data)["word/document.xml"]).findall(
                    ".//w:tab", NS
                )
            )
            == 1
        )
    old = e.undo(expected_revision=1)
    assert old.document.data == data and old.selection == before.selection
    assert e.redo(expected_revision=2).document.data == changed.document.data


@pytest.mark.parametrize("start,end", [(1, 4), (4, 1)])
def test_reverse_selection_replaces_exact_range(start, end):
    e = EditorSession(create_docx((NewParagraph("Alpha"),)))
    select(e, start, end)
    changed = e.paste_text("X\nY", expected_revision=0)
    assert [p.text for p in changed.document.projection.blocks] == ["AX", "Ya"]
    assert changed.selection.focus.offset == 1


def test_empty_replacement_and_same_text_noop_keep_source_and_redo():
    data = create_docx((NewParagraph("Alpha"),))
    e = EditorSession(data)
    select(e, 1, 4)
    removed = e.paste_text("", expected_revision=0)
    assert removed.document.projection.blocks[0].text == "Aa"
    e.undo(expected_revision=1)
    before = select(e, 1, 4)
    same = e.paste_text("lph", expected_revision=2)
    assert same.document == before.document and same.position_id == before.position_id
    assert same.selection.focus.offset == 4 and same.selection.anchor == same.selection.focus
    assert same.document.redo_depth == 1
    assert e.paste_text("", expected_revision=2) == same
    assert e.redo(expected_revision=2).document.data == removed.document.data


@pytest.mark.parametrize("style", ["heading1", "numbered", "bullet"])
def test_paste_inherits_paragraph_style_and_list_without_enter_policy(style):
    data = create_docx((NewParagraph("Alpha", style),))
    e = EditorSession(data)
    select(e, 5)
    result = e.paste_text("X\n\nY", expected_revision=0)
    blocks = result.document.projection.blocks
    assert [p.text for p in blocks] == ["AlphaX", "", "Y"]
    assert all(
        p.style_id == blocks[0].style_id and p.numbering_id == blocks[0].numbering_id
        for p in blocks
    )
    assert all(
        parts(data)[n] == parts(result.document.data)[n]
        for n in parts(data)
        if n != "word/document.xml"
    )


def test_original_inline_properties_and_trailing_empty_typing_format():
    data = source(
        "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r>"
        "<w:r><w:rPr><w:i/></w:rPr><w:t>Italic</w:t></w:r></w:p>"
    )
    e = EditorSession(data)
    s = e.snapshot()
    p0 = s.document.projection.blocks[0]
    c = Caret(p0.anchor, 4, "left")
    e.capture(EditorSelection(c, c), expected_revision=0)
    pasted = e.paste_text("X\n", expected_revision=0)
    assert [p.text for p in pasted.document.projection.blocks] == ["BoldX", "Italic"]
    typed = e.insert_text("Y", expected_revision=1)
    root = ET.fromstring(parts(typed.document.data)["word/document.xml"])
    right = root.findall("w:body/w:p", NS)[1]
    y = next(
        r
        for r in right.findall("w:r", NS)
        if r.find("w:t", NS) is not None and r.find("w:t", NS).text == "Y"
    )
    assert y.find("w:rPr/w:b", NS) is not None
    italic = next(
        r
        for r in right.findall("w:r", NS)
        if r.find("w:t", NS) is not None and r.find("w:t", NS).text == "Italic"
    )
    assert italic.find("w:rPr/w:i", NS) is not None


def test_limits_bad_text_multi_paragraph_selection_and_reply_fault_are_atomic(monkeypatch):
    module = importlib.import_module("ara.docx_package.editor")
    e = EditorSession(create_docx((NewParagraph("Alpha"), NewParagraph("Beta"))))
    before = e.snapshot()
    for limits, value in (
        (module.PasteLimits(max_text_chars=1), "XY"),
        (module.PasteLimits(max_new_paragraphs=1), "X\nY\nZ"),
    ):
        with pytest.raises(EditorError) as caught:
            e.paste_text(value, expected_revision=0, paste_limits=limits)
        assert caught.value.code == "text_limit_exceeded" and e.snapshot() == before
    for value in (None, True, "bad\x00", "bad\ud800"):
        with pytest.raises(EditorError):
            e.paste_text(value, expected_revision=0)
    with pytest.raises(SessionError):
        e.paste_text("X", expected_revision=1)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic reply failure")

    with monkeypatch.context() as patch:
        patch.setattr(EditorSnapshot, "__init__", fail)
        with pytest.raises(RuntimeError):
            e.paste_text("X\nY", expected_revision=0)
    assert e.snapshot() == before
    a, b = before.document.projection.blocks
    e.capture(EditorSelection(Caret(a.anchor, 0), Caret(b.anchor, 1)), expected_revision=0)
    before = e.snapshot()
    with pytest.raises(EditorError) as caught:
        e.paste_text("X", expected_revision=0)
    assert caught.value.code == "unsupported_intent" and e.snapshot() == before


def test_new_paragraph_identity_is_not_duplicated():
    data = source(
        '<w:p xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'w14:paraId="12345678"><w:r><w:t>Alpha</w:t></w:r></w:p>'
    )
    e = EditorSession(data)
    select(e, 2)
    result = e.paste_text("X\nY\nZ", expected_revision=0)
    assert parts(result.document.data)["word/document.xml"].count(b"12345678") == 1
    assert [p.text for p in result.document.projection.blocks] == ["AlX", "Y", "Zpha"]
