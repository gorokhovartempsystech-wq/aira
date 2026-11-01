"""Frozen D03-15B2: one user intent, one exact cursor/document history step."""

from xml.etree import ElementTree as ET

import pytest
from test_docx_boundaries import NS, p, parts, replace, source

from ara.docx_package.boundaries import BoundaryError
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.editor import (
    Caret,
    EditorError,
    EditorSelection,
    EditorSession,
    EditorSnapshot,
)
from ara.docx_package.session import SessionError, SessionLimits


def at(editor, index=0, offset=0):
    s = editor.snapshot()
    p = s.document.projection.blocks[index]
    c = Caret(p.anchor, offset)
    return editor.capture(EditorSelection(c, c), expected_revision=s.document.revision)


@pytest.mark.parametrize(
    "style,offset,expected",
    [
        ("body", 2, ["Normal", "Normal"]),
        ("heading1", 2, ["Heading1", "Heading1"]),
        ("heading1", 5, ["Heading1", "Normal"]),
        ("title", 5, ["Title", "Normal"]),
        ("numbered", 5, ["ListNumber", "ListNumber"]),
        ("bullet", 5, ["ListBullet", "ListBullet"]),
    ],
)
def test_enter_style_policy_and_single_exact_undo(style, offset, expected):
    data = create_docx((NewParagraph("Alpha", style),))
    editor = EditorSession(data)
    before = at(editor, offset=offset)
    result = editor.enter(expected_revision=0)
    blocks = result.document.projection.blocks
    assert [p.style_id for p in blocks] == expected
    assert [p.text for p in blocks] == ["Alpha"[:offset], "Alpha"[offset:]]
    assert (
        result.document.undo_depth == 1
        and result.document.revision == 1
        and result.position_id == 1
    )
    assert result.selection.focus.anchor == blocks[1].anchor and result.selection.focus.offset == 0
    if style in ("bullet", "numbered"):
        assert blocks[0].numbering_id == blocks[1].numbering_id
    undone = editor.undo(expected_revision=1)
    assert undone.document.data == data and undone.selection == before.selection
    assert editor.redo(expected_revision=2).document.data == result.document.data


@pytest.mark.parametrize("style", ["bullet", "numbered"])
def test_empty_list_exit_is_one_paragraph_and_one_undo(style):
    data = create_docx((NewParagraph("", style),))
    editor = EditorSession(data)
    before = editor.snapshot()
    result = editor.enter(expected_revision=0)
    blocks = result.document.projection.blocks
    assert len(blocks) == 1 and blocks[0].text == "" and blocks[0].numbering_id is None
    assert blocks[0].style_id == "Normal" and result.selection.focus.offset == 0
    assert result.document.undo_depth == 1
    assert editor.undo(expected_revision=1).document.data == before.document.data


def test_next_style_resets_direct_overrides_only_on_new_empty_paragraph():
    data = create_docx((NewParagraph("Heading", "heading1"),))
    old = parts(data)["word/document.xml"]
    extras = b'<w:outlineLvl w:val="0"/><w:spacing w:after="900"/><w:ind w:left="600"/>'
    data = replace(data, {"word/document.xml": old.replace(b"</w:pPr>", extras + b"</w:pPr>", 1)})
    editor = EditorSession(data)
    at(editor, offset=7)
    result = editor.enter(expected_revision=0)
    root = ET.fromstring(parts(result.document.data)["word/document.xml"])
    left, right = root.findall("w:body/w:p", NS)
    assert left.find("w:pPr/w:outlineLvl", NS) is not None
    assert len(right.find("w:pPr", NS)) == 1
    assert right.find("w:pPr/w:pStyle", NS).get("{" + NS["w"] + "}val") == "Normal"
    assert parts(data)["word/styles.xml"] == parts(result.document.data)["word/styles.xml"]


@pytest.mark.parametrize(
    "fault",
    ["missing_next", "character_next", "duplicate_next", "based_on_cycle", "inherited_list"],
)
def test_invalid_style_policy_never_publishes_intermediate_split(fault):
    data = create_docx((NewParagraph("Heading", "heading1"),))
    styles = parts(data)["word/styles.xml"]
    start = styles.index(b'<w:style w:type="paragraph" w:styleId="Heading1">')
    end = styles.index(b"</w:style>", start) + len(b"</w:style>")
    selected = styles[start:end]
    if fault == "missing_next":
        changed = selected.replace(b'<w:next w:val="Normal"/>', b'<w:next w:val="Missing"/>', 1)
        assert changed != selected
        styles = styles[:start] + changed + styles[end:]
    elif fault == "character_next":
        styles = styles.replace(
            b'w:type="paragraph" w:default="1"', b'w:type="character" w:default="1"', 1
        )
    elif fault == "duplicate_next":
        changed = selected.replace(b'<w:next w:val="Normal"/>', b'<w:next w:val="Normal"/>' * 2, 1)
        assert changed != selected
        styles = styles[:start] + changed + styles[end:]
    elif fault == "based_on_cycle":
        changed = selected.replace(
            b'<w:basedOn w:val="Normal"/>', b'<w:basedOn w:val="Heading1"/>', 1
        )
        assert changed != selected
        styles = styles[:start] + changed + styles[end:]
    else:
        styles = styles.replace(
            b"<w:widowControl/>", b'<w:numPr><w:numId w:val="1"/></w:numPr><w:widowControl/>'
        )
    data = replace(data, {"word/styles.xml": styles})
    editor = EditorSession(data)
    before = at(editor, offset=7)
    with pytest.raises(EditorError) as caught:
        editor.enter(expected_revision=0)
    assert caught.value.code == "unsupported_intent"
    assert editor.snapshot() == before


def test_no_next_and_empty_plain_paragraph_keep_style():
    editor = EditorSession(create_docx((NewParagraph("Plain"),)))
    at(editor, offset=5)
    assert [p.style_id for p in editor.enter(expected_revision=0).document.projection.blocks] == [
        "Normal",
        "Normal",
    ]
    editor = EditorSession(create_docx())
    assert len(editor.enter(expected_revision=0).document.projection.blocks) == 2


def test_join_intents_edges_and_compatibility():
    data = create_docx((NewParagraph("Left"), NewParagraph("Right")))
    editor = EditorSession(data)
    before = editor.snapshot()
    assert editor.join_previous(expected_revision=0) == before
    at(editor, 1, 5)
    before = editor.snapshot()
    assert editor.join_next(expected_revision=0) == before
    at(editor, 1, 0)
    result = editor.join_previous(expected_revision=0)
    assert (
        result.document.projection.blocks[0].text == "LeftRight"
        and result.selection.focus.offset == 4
    )
    assert editor.undo(expected_revision=1).document.data == data
    at(editor, 0, 4)
    result = editor.join_next(expected_revision=2)
    assert result.document.projection.blocks[0].text == "LeftRight"
    editor = EditorSession(create_docx((NewParagraph("Heading", "heading1"), NewParagraph("Body"))))
    at(editor, 1, 0)
    before = editor.snapshot()
    with pytest.raises(BoundaryError):
        editor.join_previous(expected_revision=0)
    assert editor.snapshot() == before


def test_range_selection_revision_and_reply_fault_are_atomic(monkeypatch):
    editor = EditorSession(create_docx((NewParagraph("Heading", "heading1"),)))
    before = at(editor, offset=7)
    for method in (editor.enter, editor.join_previous, editor.join_next):
        with pytest.raises(SessionError):
            method(expected_revision=1)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic allocation failure")

    with monkeypatch.context() as patch:
        patch.setattr(EditorSnapshot, "__init__", fail)
        with pytest.raises(RuntimeError):
            editor.enter(expected_revision=0)
    assert editor.snapshot() == before
    p = before.document.projection.blocks[0]
    editor.capture(EditorSelection(Caret(p.anchor, 0), Caret(p.anchor, 2)), expected_revision=0)
    before = editor.snapshot()
    with pytest.raises(EditorError) as caught:
        editor.enter(expected_revision=0)
    assert caught.value.code == "unsupported_intent" and editor.snapshot() == before


def test_session_budget_and_table_boundary_are_safe():
    data = create_docx((NewParagraph("Heading", "heading1"),))
    editor = EditorSession(data, session_limits=SessionLimits(max_history_bytes=len(data)))
    before = at(editor, offset=7)
    with pytest.raises(SessionError):
        editor.enter(expected_revision=0)
    assert editor.snapshot() == before
    editor = EditorSession(
        source(p("A") + "<w:tbl><w:tr><w:tc>" + p("Cell") + "</w:tc></w:tr></w:tbl>" + p("B"))
    )
    before = at(editor, 2, 0)
    with pytest.raises(BoundaryError) as caught:
        editor.join_previous(expected_revision=0)
    assert caught.value.code == "nonadjacent_paragraphs" and editor.snapshot() == before
