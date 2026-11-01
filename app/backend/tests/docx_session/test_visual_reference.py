"""Bind session export to the exact rich DOCX used for the reviewed LO render.

The fixture is synthetic. The hash pins the D02-04 visual reference; inspecting
its retained PNG remains a manual QA step, not a claim made by this test alone.
"""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from ara.docx_package.ranges import RangeEdit, TextPosition, export_docx_ranges
from ara.docx_package.session import DocxSession

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"
SOURCE_HASH = "73009626640400679d2b1a2031c565a964308073aa287067cf39088836176fcd"
RENDERED_HASH = "8c3e84f03b60b06198f1a9de7a9d3470dd1148619fff6b13db5c51f40301e2f2"


def _spans(projection):
    pending = list(projection.blocks)
    result = {}
    while pending:
        block = pending.pop()
        if block.kind == "paragraph":
            result.update((span.anchor.path, span) for span in block.spans if span.kind == "text")
        elif block.kind == "table":
            pending.extend(
                child for row in block.rows for cell in row.cells for child in cell.blocks
            )
    return result


def test_rich_session_export_matches_reviewed_render_and_preserves_properties():
    data = FIXTURE.read_bytes()
    assert sha256(data).hexdigest() == SOURCE_HASH
    session = DocxSession(data)
    initial = session.snapshot()
    old = _spans(initial.projection)
    first, second = old[(0, 4, 1, 1)], old[(0, 4, 2, 0)]
    cell, link = old[(0, 10, 5, 1, 1, 1, 1)], old[(0, 14, 1, 0, 1)]
    edits = (
        RangeEdit(
            TextPosition(first.anchor, len("stable ")),
            TextPosition(second.anchor, len(" even when")),
            "canonical type even when",
            "device type whenever",
        ),
        RangeEdit(
            TextPosition(cell.anchor, len("Kitchen ")),
            TextPosition(cell.anchor, len(cell.text)),
            "warmth",
            "heating",
        ),
        RangeEdit(
            TextPosition(link.anchor, 0),
            TextPosition(link.anchor, len("Synthetic")),
            "Synthetic",
            "Updated",
        ),
    )
    expected = {
        first.anchor.path: "stable device type whenever",
        second.anchor.path: " the display name changes. The example ",
        cell.anchor.path: "Kitchen heating",
        link.anchor.path: "Updated reference specification",
    }
    changed = session.apply(edits, expected_revision=0)
    assert changed.revision == 1 and changed.is_dirty
    assert session.undo(expected_revision=1).data == data
    replayed = session.redo(expected_revision=2)
    assert replayed.data == changed.data and replayed.revision == 3
    saved = session.mark_saved(expected_revision=3)
    assert saved.data == changed.data and not saved.is_dirty
    assert initial.data == data and initial.revision == 0
    result = replayed.data
    assert result == export_docx_ranges(data, edits)
    assert result == export_docx_ranges(data, tuple(reversed(edits)))
    assert sha256(result).hexdigest() == RENDERED_HASH

    new = _spans(replayed.projection)
    assert new.keys() == old.keys()
    for path, span in old.items():
        assert new[path].text == expected.get(path, span.text)

    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(result)) as after:
        assert before.namelist() == after.namelist()
        assert before.comment == after.comment
        main = initial.projection.source.main_part
        unchanged = 0
        for name in before.namelist():
            if name != main:
                assert before.read(name) == after.read(name)
                unchanged += 1
            left, right = before.getinfo(name), after.getinfo(name)
            for attr in (
                "date_time",
                "compress_type",
                "comment",
                "create_system",
                "external_attr",
                "internal_attr",
            ):
                assert getattr(left, attr) == getattr(right, attr)
        assert unchanged == 19
        before_root, after_root = ET.fromstring(before.read(main)), ET.fromstring(after.read(main))
        for path, replacement in expected.items():
            left, right = before_root, after_root
            for index in path:
                left, right = left[index], right[index]
            assert right.text == replacement
            assert right.attrib == {
                **left.attrib,
                "{http://www.w3.org/XML/1998/namespace}space": "preserve",
            }
            right.text = left.text
            right.attrib.clear()
            right.attrib.update(left.attrib)
        assert ET.tostring(before_root) == ET.tostring(after_root)
