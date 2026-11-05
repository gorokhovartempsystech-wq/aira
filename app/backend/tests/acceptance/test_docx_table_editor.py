"""Fixed opt-in cell selection, lexical edits and recoverable original Word packages."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from uuid import UUID

import pytest
from test_docx_visible_main import source as minimal
from test_docx_visible_word import parts, source

from ara.docx_package.checkpoint import (
    CheckpointMetadata,
    CheckpointOrigin,
    decode_metadata,
    encode_metadata,
)
from ara.docx_package.editor import Caret, EditorError, EditorSelection, EditorSession


def p(text):
    return "<w:p><w:r><w:t>" + text + "</w:t></w:r></w:p>"


def api():
    return import_module("ara.docx_package.table_editor").TableEditorSession


def paragraphs(projection):
    def walk(blocks):
        for block in blocks:
            if block.kind == "paragraph":
                yield block
            elif block.kind == "table":
                for row in block.rows:
                    for cell in row.cells:
                        yield from walk(cell.blocks)

    return tuple(walk(projection.blocks))


@pytest.mark.parametrize("case", ["table", "merged_table"])
def test_table_only_opens_without_changing_bytes_and_legacy_still_refuses(case):
    raw = source(case)
    with pytest.raises(EditorError):
        EditorSession(raw)
    e = api()(raw)
    s = e.snapshot()
    first = paragraphs(s.document.projection)[0]
    assert s.document.data == raw and s.selection.anchor == Caret(first.anchor, 0)
    assert s.selection.focus == s.selection.anchor and not s.document.is_dirty
    assert all(b.kind != "paragraph" for b in s.document.projection.blocks)


@pytest.mark.parametrize("case", ["plain", "numbered", "headings"])
def test_body_initial_state_and_typing_keep_prior_bytes(case):
    raw = source(case)
    old, new = EditorSession(raw), api()(raw)
    assert old.snapshot() == new.snapshot()
    assert old.insert_text("Новый ", expected_revision=0) == new.insert_text(
        "Новый ", expected_revision=0
    )


@pytest.mark.parametrize("case", ["table", "merged_table"])
def test_cell_unicode_replace_undo_redo_and_other_parts_unchanged(case):
    raw = source(case)
    e = api()(raw)
    before = e.snapshot()
    first = paragraphs(before.document.projection)[0]
    selected = EditorSelection(Caret(first.anchor, 1), Caret(first.anchor, 3))
    e.capture(selected, expected_revision=0)
    saved_before = e.snapshot()
    changed = e.insert_text("🧪 & новый", expected_revision=0)
    current = paragraphs(changed.document.projection)[0]
    assert current.text == first.text[:1] + "🧪 & новый" + first.text[3:]
    assert changed.selection.anchor.offset == 1 + len("🧪 & новый")
    assert changed.document.is_dirty and changed.document.revision == 1
    a, b = parts(raw), parts(changed.document.data)
    assert a.keys() == b.keys() and all(a[k] == b[k] for k in a if k != "word/document.xml")
    assert [p.text for p in paragraphs(changed.document.projection)[1:]] == [
        p.text for p in paragraphs(before.document.projection)[1:]
    ]
    undone = e.undo(expected_revision=1)
    assert undone.document.data == raw and undone.selection == saved_before.selection
    assert e.redo(expected_revision=2).document.data == changed.document.data


def test_empty_cell_can_type_and_soft_break_keeps_table_shape():
    raw = minimal("<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>")[0]
    e = api()(raw)
    s = e.insert_text("Alpha😀", expected_revision=0)
    s = e.insert_soft_break(expected_revision=1)
    s = e.insert_text("Beta", expected_revision=2)
    assert paragraphs(s.document.projection)[0].text == "Alpha😀\nBeta"
    assert (
        len(s.document.projection.blocks) == 1 and s.document.projection.blocks[0].kind == "table"
    )


def test_nested_table_initial_order_and_metadata_round_trip_restore():
    inner = "<w:tbl><w:tr><w:tc>" + p("Nested") + "</w:tc></w:tr></w:tbl>"
    raw = minimal("<w:tbl><w:tr><w:tc>" + inner + p("Outer") + "</w:tc></w:tr></w:tbl>")[0]
    e = api()(raw)
    assert paragraphs(e.snapshot().document.projection)[0].text == "Nested"
    s = e.insert_text("New ", expected_revision=0)
    meta = CheckpointMetadata(
        s.selection, CheckpointOrigin(UUID(int=1), s.document.revision, s.position_id)
    )
    base = sha256(raw).hexdigest()
    wire = encode_metadata(meta, data=s.document.data, saved_sha256=base, phase="working")
    decoded = decode_metadata(wire, data=s.document.data, saved_sha256=base, phase="working")
    restored = (
        api().restore(s.document.data, saved_sha256=base, selection=decoded.selection).snapshot()
    )
    assert restored.document.data == s.document.data and restored.selection == s.selection
    assert restored.document.is_dirty and restored.document.revision == restored.position_id == 0
    assert restored.document.undo_depth == restored.document.redo_depth == 0
    with pytest.raises(EditorError):
        EditorSession.restore(s.document.data, saved_sha256=base, selection=decoded.selection)


@pytest.mark.parametrize("bad", ["source", "part", "offset", "path"])
def test_invalid_cell_selection_never_changes_editor(bad):
    e = api()(source("table"))
    before = e.snapshot()
    point = before.selection.anchor
    a = point.anchor
    a = replace(
        a,
        **(
            {"source_sha256": "0" * 64}
            if bad == "source"
            else {"part_name": "word/header1.xml"}
            if bad == "part"
            else {"path": (999,)}
            if bad == "path"
            else {}
        ),
    )
    point = replace(point, anchor=a, offset=999 if bad == "offset" else 0)
    with pytest.raises(EditorError):
        e.capture(EditorSelection(point, point), expected_revision=0)
    assert e.snapshot() == before


@pytest.mark.parametrize("action", ["enter", "join_previous", "join_next", "paste_text"])
def test_unsupported_cell_structure_is_explicit_and_atomic(action):
    e = api()(source("table"))
    before = e.snapshot()
    args = ("A\nB",) if action == "paste_text" else ()
    with pytest.raises(EditorError) as exc:
        getattr(e, action)(*args, expected_revision=0)
    assert exc.value.code == "unsupported_intent" and e.snapshot() == before


def test_cross_cell_replace_is_rejected_without_moving_selection_or_changing_text():
    e = api()(source("table"))
    ps = paragraphs(e.snapshot().document.projection)
    e.capture(EditorSelection(Caret(ps[0].anchor, 0), Caret(ps[1].anchor, 1)), expected_revision=0)
    before = e.snapshot()
    with pytest.raises(EditorError) as exc:
        e.insert_text("Replacement", expected_revision=0)
    assert exc.value.code == "unsupported_intent" and e.snapshot() == before


@pytest.mark.parametrize(
    "method,args", [("paste_text", ("A\nB",)), ("enter", ()), ("insert_soft_break", ())]
)
def test_opt_in_body_command_outputs_remain_identical(method, args):
    raw = source("plain")
    old, new = EditorSession(raw), api()(raw)
    assert getattr(old, method)(*args, expected_revision=0) == getattr(new, method)(
        *args, expected_revision=0
    )


def test_cell_formatting_is_retained_and_bytes_outside_target_paragraph_unchanged():
    from ara.docx_package.boundaries import BoundaryLimits
    from ara.docx_package.boundaries._tree import Tree

    raw = minimal(
        '<w:tbl><w:tr><w:tc><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
        '<w:r><w:rPr><w:b/><w:color w:val="123456"/></w:rPr>'
        "<w:t>Alpha</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )[0]
    e = api()(raw)
    before = e.snapshot().document
    changed = e.insert_text("X", expected_revision=0).document
    name = before.projection.source.main_part
    a, b = parts(raw)[name], parts(changed.data)[name]
    p, q = paragraphs(before.projection)[0], paragraphs(changed.projection)[0]
    ta, tb = Tree(a, (p,), BoundaryLimits()), Tree(b, (q,), BoundaryLimits())
    na, nb = ta.nodes[p.anchor.path], tb.nodes[q.anchor.path]
    assert a[: na.start] == b[: nb.start] and a[na.end :] == b[nb.end :]
    assert b.count(b"<w:b/>") >= 1 and b.count(b'w:val="123456"') >= 1
    assert b'<w:pPr><w:jc w:val="center"/></w:pPr>' in b


@pytest.mark.parametrize("bad", ["hyperlink", "annotation", "field"])
def test_unsupported_cell_content_refuses_without_partial_rewrite(bad):
    child = {
        "hyperlink": '<w:hyperlink w:anchor="target"><w:r><w:t>Alpha</w:t></w:r></w:hyperlink>',
        "annotation": "<!-- private annotation --><w:r><w:t>Alpha</w:t></w:r>",
        "field": '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>',
    }[bad]
    raw = minimal("<w:tbl><w:tr><w:tc><w:p>" + child + "</w:p></w:tc></w:tr></w:tbl>")[0]
    e = api()(raw)
    before = e.snapshot()
    from ara.docx_package.boundaries import BoundaryError

    with pytest.raises(BoundaryError):
        e.insert_text("X", expected_revision=0)
    assert e.snapshot() == before


def test_cell_single_line_paste_noop_and_stale_revision():
    from ara.docx_package.session import SessionError

    e = api()(source("table"))
    first = e.snapshot()
    assert e.insert_text("", expected_revision=0) == first
    after = e.paste_text("Text", expected_revision=0)
    with pytest.raises(SessionError) as exc:
        e.insert_text("Wrong", expected_revision=0)
    assert exc.value.code == "stale_revision" and e.snapshot() == after


def test_changed_source_cannot_reuse_checkpoint_selection():
    e = api()(source("table"))
    first = e.snapshot()
    new = e.insert_text("New", expected_revision=0)
    meta = CheckpointMetadata(first.selection, CheckpointOrigin(UUID(int=1), 0, 0))
    with pytest.raises(EditorError) as exc:
        encode_metadata(
            meta,
            data=new.document.data,
            saved_sha256=sha256(first.document.data).hexdigest(),
            phase="working",
        )
    assert exc.value.code == "stale_selection"


@pytest.mark.parametrize("body", ["", '<w:altChunk xmlns:r="urn:unused"/>'])
def test_missing_projected_paragraph_does_not_invent_a_cell_or_body(body):
    raw = minimal(body)[0]
    with pytest.raises(EditorError) as exc:
        api()(raw)
    assert exc.value.code == "invalid_selection"
