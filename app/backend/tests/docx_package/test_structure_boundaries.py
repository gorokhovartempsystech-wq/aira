"""Additional D03-11 regression cases on rich packages and lower limits."""

import io
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.projection import ProjectionError, ProjectionLimits, project_docx
from ara.docx_package.structure import (
    DeleteParagraph,
    InsertParagraph,
    StructureError,
    export_structure,
)


def test_rich_source_tables_media_and_all_untouched_parts_survive():
    path = Path(__file__).resolve().parents[1] / "fixtures/docx/rich-source.docx"
    original = path.read_bytes()
    view = project_docx(original)
    paras = [p for p in view.blocks if p.kind == "paragraph"]
    commands = (
        InsertParagraph(paras[0].anchor, paras[0].text, ("Synthetic insertion", ""), "before"),
        DeleteParagraph(paras[1].anchor, paras[1].text),
    )
    result = export_structure(original, commands)
    after = project_docx(result)
    assert [b.text for b in after.blocks if b.kind == "paragraph"] == [
        "Synthetic insertion",
        "",
        *[p.text for p in paras if p is not paras[1]],
    ]
    with ZipFile(io.BytesIO(original)) as a, ZipFile(io.BytesIO(result)) as b:
        assert a.namelist() == b.namelist()
        unchanged = [n for n in a.namelist() if n != view.source.main_part]
        assert len(unchanged) == 19
        assert all(a.read(n) == b.read(n) for n in unchanged)
    assert len([b for b in view.blocks if b.kind == "table"]) == len(
        [b for b in after.blocks if b.kind == "table"]
    )


def test_output_projection_limit_is_not_bypassed_by_a_small_valid_input():
    raw = create_docx()
    with ZipFile(io.BytesIO(raw)) as archive:
        count = sum(1 for _ in ET.fromstring(archive.read("word/document.xml")).iter())
    p = project_docx(raw).blocks[0]
    with pytest.raises(ProjectionError) as caught:
        export_structure(
            raw,
            (InsertParagraph(p.anchor, p.text, ("new",)),),
            projection_limits=ProjectionLimits(max_nodes=count),
        )
    assert caught.value.code == "projection_limit_exceeded"


def test_other_valid_encoding_is_noop_only():
    raw = create_docx((NewParagraph("ASCII only"),))
    output = io.BytesIO()
    with ZipFile(io.BytesIO(raw)) as source, ZipFile(output, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "word/document.xml":
                data = data.replace(b'encoding="UTF-8"', b'encoding="ISO-8859-1"')
            target.writestr(info, data)
    raw = output.getvalue()
    p = project_docx(raw).blocks[0]
    assert export_structure(raw, ()) == raw
    with pytest.raises(StructureError) as caught:
        export_structure(raw, (InsertParagraph(p.anchor, p.text),))
    assert caught.value.code == "unsupported_structure"


def test_adjacent_deletions_preserve_one_paragraph_and_ignore_command_order():
    raw = create_docx(tuple(NewParagraph(s) for s in ("one", "two", "three")))
    paras = project_docx(raw).blocks
    commands = tuple(DeleteParagraph(p.anchor, p.text) for p in paras[:2])
    changed = export_structure(raw, commands)
    assert changed == export_structure(raw, tuple(reversed(commands)))
    assert [p.text for p in project_docx(changed).blocks] == ["three"]
