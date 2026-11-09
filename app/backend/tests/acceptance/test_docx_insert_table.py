"""Table insertion is a single source-preserving editor operation."""

import pytest
from test_docx_visible_word import build, parts

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.editor import Caret, EditorError, EditorSelection
from ara.docx_package.table_editor import TableEditorSession


def editor():
    e = TableEditorSession(create_docx((NewParagraph("", "body"),)))
    e.insert_text("Left😀Right", expected_revision=0)
    s = e.snapshot()
    p = s.document.projection.blocks[0]
    point = Caret(p.anchor, 5)
    e.capture(EditorSelection(point, point), expected_revision=1)
    return e


def test_insert_table_splits_unicode_preserves_package_and_single_undo():
    e = editor()
    before = e.snapshot().document
    s = e.insert_table(2, 3, expected_revision=before.revision)
    blocks = s.document.projection.blocks
    assert [(b.kind, getattr(b, "text", "")) for b in blocks] == [
        ("paragraph", "Left😀"),
        ("table", ""),
        ("paragraph", "Right"),
    ]
    t = blocks[1]
    assert len(t.rows) == 2 and all(len(r.cells) == 3 for r in t.rows)
    assert all(c.blocks[0].text == "" for r in t.rows for c in r.cells)
    assert s.selection.anchor.anchor == blocks[2].anchor and s.selection.anchor.offset == 0
    assert s.document.undo_depth == before.undo_depth + 1
    old = parts(before.data)
    new = parts(s.document.data)
    assert old.keys() == new.keys()
    assert all(old[n] == new[n] for n in old if n != before.projection.source.main_part)
    assert build(s.document.data).complete
    inserted = s.document.data
    u = e.undo(expected_revision=s.document.revision)
    assert u.document.data == before.data and u.selection.anchor.offset == 5
    r = e.redo(expected_revision=u.document.revision)
    assert r.document.data == inserted


def test_new_cells_remain_editable_and_restore_from_saved_bytes():
    e = editor()
    s = e.insert_table(1, 1, expected_revision=1)
    p = s.document.projection.blocks[1].rows[0].cells[0].blocks[0]
    point = Caret(p.anchor, 0)
    e.capture(EditorSelection(point, point), expected_revision=s.document.revision)
    s = e.insert_text("Requirement😀", expected_revision=s.document.revision)
    again = TableEditorSession(s.document.data)
    assert (
        again.snapshot().document.projection.blocks[1].rows[0].cells[0].blocks[0].text
        == "Requirement😀"
    )
    assert "Requirement😀" in build(s.document.data).analysis_text


@pytest.mark.parametrize(
    "rows,columns", [(0, 1), (1, 0), (True, 2), (101, 1), (1, 33), (100, 32), ("2", 2)]
)
def test_bad_table_size_does_not_change_bytes_or_history(rows, columns):
    e = editor()
    before = e.snapshot()
    with pytest.raises(EditorError):
        e.insert_table(rows, columns, expected_revision=1)
    assert e.snapshot() == before


def test_stale_revision_does_not_insert_a_second_table():
    e = editor()
    s = e.insert_table(2, 2, expected_revision=1)
    with pytest.raises(ValueError):
        e.insert_table(2, 2, expected_revision=1)
    assert e.snapshot() == s


def test_table_http_replay_save_and_reopen(run_world):
    from fastapi.testclient import TestClient
    from test_desktop_structured_review import imported
    from test_docx_editor_http import command, control, opened, path, root

    from ara.app import create_app

    raw = create_docx((NewParagraph("Text", "body"),))
    with TestClient(
        create_app(document_runtime=run_world["runtimes"]["own"], table_editor=True)
    ) as http:
        item = imported(http, raw)
        view, _ = opened(http, item)
        payload = command(view, "insert_table", {"rows": 2, "columns": 3})
        response = http.post(path(item, view) + "/commands", json=payload)
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["document"]["undo_depth"] == 1
        assert http.post(path(item, view) + "/commands", json=payload).json() == changed
        stale = command(view, "insert_table", {"rows": 2, "columns": 3})
        assert http.post(path(item, view) + "/commands", json=stale).status_code == 409
        saved = http.post(path(item, view) + "/save", json=control(changed))
        assert saved.status_code == 200, saved.text
        data = http.get(root(item) + "/content").content
        table = TableEditorSession(data).snapshot().document.projection.blocks[1]
        assert table.kind == "table" and len(table.rows) == 2 and len(table.rows[0].cells) == 3
        assert build(data).complete
        assert http.post(path(item, view) + "/close", json=control(saved.json())).status_code == 200
        recovered, _ = opened(http, item, "recover")
        assert recovered["base_sha256"] == saved.json()["base_sha256"]
        assert http.get(root(item) + "/content").content == data


def test_expanded_selection_refuses_without_history_change():
    e = editor()
    s = e.snapshot()
    p = s.document.projection.blocks[0]
    e.capture(EditorSelection(Caret(p.anchor, 1), Caret(p.anchor, 3)), expected_revision=1)
    before = e.snapshot()
    with pytest.raises(EditorError):
        e.insert_table(1, 1, expected_revision=1)
    assert e.snapshot() == before


def test_table_obeys_narrow_section_width():
    from xml.etree import ElementTree as E

    from test_docx_visible_word import W, alter

    raw = create_docx((NewParagraph("", "body"),))

    def narrow(root):
        section = root.find(".//" + W + "sectPr")
        section.find(W + "pgSz").set(W + "w", "6000")
        margins = section.find(W + "pgMar")
        margins.set(W + "left", "1000")
        margins.set(W + "right", "1000")

    e = TableEditorSession(alter(raw, "word/document.xml", narrow))
    s = e.insert_table(2, 3, expected_revision=0)
    tree = E.fromstring(parts(s.document.data)["word/document.xml"])
    widths = [int(n.get(W + "w")) for n in tree.iter(W + "gridCol")]
    assert sum(widths) == 4000 and max(widths) - min(widths) <= 1


def test_malformed_native_size_is_rejected_as_validation_error():
    from ara.documents.storage import DocumentError
    from ara.docx_editor import EditorCommand
    from ara.docx_package.editor._objects import TableSize

    with pytest.raises(DocumentError) as exc:
        EditorCommand("insert_table", object.__new__(TableSize))
    assert exc.value.status == 422
