import io
import zipfile

import pytest
from test_docx_visible_fields import char, complex_field, instr, run
from test_docx_visible_main import source
from test_docx_visible_notes import literal

from ara.docx_package.boundaries import BoundaryError
from ara.docx_package.editor import EditorError
from ara.docx_package.projection import ProjectionLimits, project_docx
from ara.docx_package.table_editor.field_safe import FieldSafeTableEditorSession


def p(content):
    return "<w:p>" + content + "</w:p>"


def projection(body):
    raw = source(body)[0]
    return raw, project_docx(raw, projection_limits=ProjectionLimits(isolate_complex_fields=True))


def test_protect_fields_leave_other_paragraphs_and_preserve_original():
    raw, v = projection(
        p(run(literal("Before"))) + p(run(complex_field())) + p(run(literal("After")))
    )
    assert [b.kind for b in v.blocks] == ["paragraph", "opaque", "paragraph"]
    assert len(project_docx(raw).blocks) == 1  # Existing conservative default unchanged.
    editor = FieldSafeTableEditorSession(raw)
    assert editor.snapshot().document.data == raw
    editor.insert_text("Added ", expected_revision=0)
    modified = editor.snapshot().document.data
    main = editor.snapshot().document.projection.source.main_part
    with zipfile.ZipFile(io.BytesIO(raw)) as a, zipfile.ZipFile(io.BytesIO(modified)) as b:
        assert a.namelist() == b.namelist()
        assert all(a.read(n) == b.read(n) for n in a.namelist() if n != main)
        assert b"fldChar" in b.read(main)
    assert editor.snapshot().document.projection.blocks[1].kind == "opaque"


def test_cross_paragraph_field_keeps_entire_interval_opaque():
    _, v = projection(
        p(run(literal("Before")))
        + p(run(char("begin") + instr()))
        + p(run(char("separate") + literal("Cached")))
        + p(run(char("end")))
        + p(run(literal("After")))
    )
    assert [b.kind for b in v.blocks] == ["paragraph", "opaque", "opaque", "opaque", "paragraph"]


@pytest.mark.parametrize(
    "field",
    [
        char("end"),
        char("begin"),
        instr(),
        char("begin") + char("separate") + char("separate") + char("end"),
    ],
)
def test_malformed_fields_keep_whole_body_protected(field):
    raw, v = projection(p(run(literal("Before"))) + p(run(field)))
    assert len(v.blocks) == 1 and v.blocks[0].kind == "opaque"
    with pytest.raises(EditorError):
        FieldSafeTableEditorSession(raw)


@pytest.mark.parametrize("marker", ["commentRangeStart", "permStart", "ins"])
def test_opt_in_does_not_allow_unrelated_unsafe_global_markup(marker):
    raw = source(p(run(literal("Before"))) + p(f'<w:{marker} w:id="1"/>' + run(literal("Other"))))[
        0
    ]
    editor = FieldSafeTableEditorSession(raw)
    with pytest.raises((EditorError, BoundaryError)) as caught:
        editor.insert_text("No change", expected_revision=0)
    assert getattr(caught.value, "code", None) == "unsupported_boundary"
    assert editor.snapshot().document.data == raw
