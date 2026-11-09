"""Embedded image insertion preserves package ownership and editor history."""

from xml.etree import ElementTree as E

import pytest
from test_docx_insert_table import editor
from test_docx_visible_inline_images import JPEG_BASELINE, JPEG_PROGRESSIVE, png
from test_docx_visible_word import build, parts

from ara.docx_package.editor import EditorError


@pytest.mark.parametrize(
    "image,mime",
    [(png(), "image/png"), (JPEG_BASELINE, "image/jpeg"), (JPEG_PROGRESSIVE, "image/jpeg")],
)
def test_image_insertion_preserves_bytes_relationship_and_single_undo(image, mime):
    e = editor()
    before = e.snapshot()
    s = e.insert_image(image, alt_text='Diagram & "status"', expected_revision=1)
    blocks = s.document.projection.blocks
    assert blocks[0].text == "Left😀" and blocks[2].text == "Right"
    assert s.document.undo_depth == before.document.undo_depth + 1
    entries = {p.name: p for p in s.document.projection.source.entries}
    media = [p for p in entries.values() if p.content_type == mime]
    assert len(media) == 1 and parts(s.document.data)[media[0].name] == image
    old = parts(before.document.data)
    current = parts(s.document.data)
    allowed = {
        before.document.projection.source.main_part,
        "[Content_Types].xml",
        "word/_rels/document.xml.rels",
    }
    assert all(current[n] == old[n] for n in old if n not in allowed)
    link = [
        r
        for r in s.document.projection.source.relationships
        if r.relationship_type.endswith("/image")
    ]
    assert (
        len(link) == 1
        and link[0].resolved_part == media[0].name
        and link[0].target_mode == "Internal"
    )
    root = E.fromstring(current[s.document.projection.source.main_part])
    docpr = next(n for n in root.iter() if n.tag.endswith("}docPr"))
    assert docpr.get("descr") == 'Diagram & "status"'
    analysis = build(s.document.data)
    assert not analysis.complete
    assert any(c.code == "unsupported_image_alternative_text" for c in analysis.coverage)
    inserted = s.document.data
    u = e.undo(expected_revision=s.document.revision)
    assert u.document.data == before.document.data and u.selection == before.selection
    r = e.redo(expected_revision=u.document.revision)
    assert r.document.data == inserted


def test_repeated_image_reuses_media_without_reusing_drawing_identity():
    e = editor()
    first = e.insert_image(png(), expected_revision=1)
    second = e.insert_image(png(), expected_revision=first.document.revision)
    images = [p for p in second.document.projection.source.entries if p.content_type == "image/png"]
    assert len(images) == 1
    root = E.fromstring(parts(second.document.data)[second.document.projection.source.main_part])
    ids = [n.get("id") for n in root.iter() if n.tag.endswith("}docPr")]
    assert len(ids) == len(set(ids)) == 2


@pytest.mark.parametrize(
    "bad", [b"", b"not an image", b"<svg/>", png()[:-4], JPEG_BASELINE[:-2], "path.png"]
)
def test_bad_image_cannot_change_document_or_history(bad):
    e = editor()
    before = e.snapshot()
    with pytest.raises(ValueError):
        e.insert_image(bad, expected_revision=1)
    assert e.snapshot() == before


def test_invalid_alt_text_does_not_change_document():
    e = editor()
    before = e.snapshot()
    with pytest.raises(EditorError):
        e.insert_image(png(), alt_text="bad\x00text", expected_revision=1)
    assert e.snapshot() == before


@pytest.mark.parametrize("image", [png(), JPEG_BASELINE, JPEG_PROGRESSIVE])
def test_image_without_alt_preserves_complete_visible_text(image):
    e = editor()
    s = e.insert_image(image, expected_revision=1)
    snapshot = build(s.document.data)
    assert snapshot.complete
    assert [f.text for f in snapshot.fragments if f.text.strip()] == ["Left😀", "Right"]


def test_image_http_replay_save_reopen_and_bad_payload(run_world):
    from base64 import b64encode

    from fastapi.testclient import TestClient
    from test_desktop_structured_review import imported
    from test_docx_editor_http import command, control, opened, path, root

    from ara.app import create_app
    from ara.docx_package.creation import NewParagraph, create_docx
    from ara.docx_package.table_editor import TableEditorSession

    raw = create_docx((NewParagraph("Text", "body"),))
    with TestClient(
        create_app(document_runtime=run_world["runtimes"]["own"], table_editor=True)
    ) as http:
        item = imported(http, raw)
        view, _ = opened(http, item)
        for invalid in (
            {"data_base64": "!"},
            {"data_base64": "AAAA", "path": "secret.png"},
            {"data_base64": ""},
        ):
            assert (
                http.post(
                    path(item, view) + "/commands", json=command(view, "insert_image", invalid)
                ).status_code
                == 422
            )
        payload = command(view, "insert_image", {"data_base64": b64encode(png()).decode()})
        response = http.post(path(item, view) + "/commands", json=payload)
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["document"]["undo_depth"] == 1
        assert http.post(path(item, view) + "/commands", json=payload).json() == changed
        assert (
            http.post(
                path(item, view) + "/commands",
                json=command(view, "insert_image", payload["command"]["value"]),
            ).status_code
            == 409
        )
        saved = http.post(path(item, view) + "/save", json=control(changed))
        assert saved.status_code == 200, saved.text
        data = http.get(root(item) + "/content").content
        again = TableEditorSession(data).snapshot()
        assert any(p.content_type == "image/png" for p in again.document.projection.source.entries)
        assert build(data).complete
        assert http.post(path(item, view) + "/close", json=control(saved.json())).status_code == 200
        recovered, _ = opened(http, item, "recover")
        assert recovered["base_sha256"] == saved.json()["base_sha256"]
        assert http.get(root(item) + "/content").content == data


def test_image_size_limits_and_selection_fail_atomically():
    import struct

    from test_docx_visible_inline_images import chunk

    from ara.docx_package.editor import Caret, EditorSelection

    huge = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 10000, 10000, 8, 2, 0, 0, 0))
        + png()[33:]
    )
    e = editor()
    for bad in (huge, b"x" * (4 * 1024 * 1024 + 1)):
        before = e.snapshot()
        with pytest.raises(EditorError):
            e.insert_image(bad, expected_revision=1)
        assert e.snapshot() == before
    p = e.snapshot().document.projection.blocks[0]
    e.capture(EditorSelection(Caret(p.anchor, 1), Caret(p.anchor, 2)), expected_revision=1)
    before = e.snapshot()
    with pytest.raises(EditorError):
        e.insert_image(png(), expected_revision=1)
    assert e.snapshot() == before


def test_stale_image_insertion_cannot_create_second_resource():
    e = editor()
    current = e.insert_image(png(), expected_revision=1)
    with pytest.raises(ValueError):
        e.insert_image(JPEG_BASELINE, expected_revision=1)
    assert e.snapshot() == current


def test_image_respects_section_width_height_and_aspect():
    import struct
    import zlib

    from test_docx_visible_inline_images import chunk
    from test_docx_visible_word import W, alter

    from ara.docx_package.creation import NewParagraph, create_docx
    from ara.docx_package.table_editor import TableEditorSession

    wide = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1200, 600, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x10\x20\x30" * 1200) * 600))
        + chunk(b"IEND", b"")
    )
    raw = create_docx((NewParagraph("", "body"),))

    def narrow(root):
        section = root.find(".//" + W + "sectPr")
        section.find(W + "pgSz").set(W + "w", "5000")
        section.find(W + "pgSz").set(W + "h", "4000")
        margins = section.find(W + "pgMar")
        for side in ("left", "right", "top", "bottom"):
            margins.set(W + side, "1000")

    e = TableEditorSession(alter(raw, "word/document.xml", narrow))
    s = e.insert_image(wide, expected_revision=0)
    root = E.fromstring(parts(s.document.data)["word/document.xml"])
    extent = next(n for n in root.iter() if n.tag.endswith("}extent"))
    cx, cy = int(extent.get("cx")), int(extent.get("cy"))
    assert cx <= 3000 * 635 and cy <= 2000 * 635 and cx == 2 * cy
    assert (
        parts(s.document.data)[
            next(
                p.name
                for p in s.document.projection.source.entries
                if p.content_type == "image/png"
            )
        ]
        == wide
    )


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_image_with_nonstandard_main_part_and_new_relationship_file(strict, encoding):
    from test_docx_compatibility_contexts import fixture

    from ara.docx_package.table_editor import TableEditorSession

    raw, _ = fixture(
        "<w:p><w:r><w:t>Requirement</w:t></w:r></w:p>", strict=strict, encoding=encoding
    )
    e = TableEditorSession(raw)
    s = e.insert_image(png(), expected_revision=0)
    main = s.document.projection.source.main_part
    assert main == "custom/Main.xml"
    assert build(s.document.data).complete
    assert build(s.document.data).analysis_text.strip() == "Requirement"
    assert e.undo(expected_revision=1).document.data == raw


def test_image_never_overwrites_existing_resources_and_allocates_numeric_id():
    from test_docx_visible_inline_images import drawing, source

    from ara.docx_package.table_editor import TableEditorSession

    body = (
        "<w:p><w:r><w:t>Before</w:t></w:r></w:p><w:p><w:r>"
        + drawing().replace('id="1"', 'id="01"')
        + "</w:r></w:p>"
    )
    raw, _ = source(body)
    e = TableEditorSession(raw)
    s = e.insert_image(JPEG_BASELINE, expected_revision=0)
    old, new = parts(raw), parts(s.document.data)
    for name, value in old.items():
        if name not in ("[Content_Types].xml", "custom/Main.xml", "custom/_rels/Main.xml.rels"):
            assert new[name] == value
    root = E.fromstring(new["custom/Main.xml"])
    ids = [int(n.get("id")) for n in root.iter() if n.tag.endswith("}docPr")]
    assert sorted(ids) == [1, 2]


def test_image_refuses_cell_position_and_protected_package_without_mutation():
    from test_docx_compatibility_contexts import fixture

    from ara.docx_package.editor import Caret, EditorSelection
    from ara.docx_package.table_editor import TableEditorSession

    e = editor()
    s = e.insert_table(1, 1, expected_revision=1)
    p = s.document.projection.blocks[1].rows[0].cells[0].blocks[0]
    point = Caret(p.anchor, 0)
    e.capture(EditorSelection(point, point), expected_revision=2)
    before = e.snapshot()
    with pytest.raises(ValueError):
        e.insert_image(png(), expected_revision=2)
    assert e.snapshot() == before
    raw, _ = fixture(
        "<w:p/>", settings='<w:documentProtection w:edit="readOnly" w:enforcement="1"/>'
    )
    e = TableEditorSession(raw)
    before = e.snapshot()
    with pytest.raises(ValueError):
        e.insert_image(png(), expected_revision=0)
    assert e.snapshot() == before


def test_package_additions_cannot_replace_existing_or_exceed_limit():
    from dataclasses import replace

    from ara.docx_package import DocxLimits
    from ara.docx_package.structure._package import repack_parts

    e = editor()
    s = e.snapshot().document
    limits = DocxLimits()
    for addition in ({s.projection.source.main_part: b"x"}, {"../escape": b"x"}, {"new.bin": b"x"}):
        bounded = (
            replace(limits, max_entries=len(s.projection.source.entries))
            if "new.bin" in addition
            else limits
        )
        with pytest.raises(ValueError):
            repack_parts(s.data, s.projection.source, {}, bounded, additions=addition)
    assert e.snapshot().document.data == s.data


def test_inserted_opc_metadata_uses_office_compatible_default_namespace():
    # LibreOffice rejected prefixed Relationship/Override, even with the correct URI.
    # Both additions must use the default namespace; existing metadata remains lexical.
    from ara.docx_package.boundaries import BoundaryLimits
    from ara.docx_package.boundaries._tree import Tree

    e = editor()
    s = e.insert_image(png(), expected_revision=1)
    content = parts(s.document.data)
    for name, local in (
        ("[Content_Types].xml", "Override"),
        ("word/_rels/document.xml.rels", "Relationship"),
    ):
        tree = Tree(content[name], (), BoundaryLimits())
        added = [
            n
            for n in tree.nodes.values()
            if n.name.endswith("}" + local)
            and (
                n.attrs.get("ContentType") == "image/png"
                or n.attrs.get("Id", "").startswith("rIdAira")
            )
        ]
        assert len(added) == 1 and tree.qualified(added[0]) == local
