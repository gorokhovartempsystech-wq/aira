"""Read stored field results without interpreting or executing field instructions."""

from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

import pytest
from test_docx_note_catalog import note
from test_docx_section_catalog import BASE, reference, section
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_main import DOC, R, canonical, codes, payload, source
from test_docx_visible_notes import fixture as notes_fixture
from test_docx_visible_notes import literal, p, ref
from test_docx_visible_stories import story_xml

PROFILE = "docx-analysis/final-visible-field-results-v1"


def api():
    return import_module("ara.docx_analysis.visible_fields")


def run(content):
    return "<w:r>" + content + "</w:r>"


def char(kind, attrs=""):
    return f'<w:fldChar w:fldCharType="{kind}"{attrs}/>'


def instr(text="AUTHOR"):
    return '<w:instrText xml:space="preserve">' + text + "</w:instrText>"


def simple(content=None, command="AUTHOR", attrs=""):
    content = run(literal("Cached")) if content is None else content
    return f"<w:fldSimple w:instr={quoteattr(command)}{attrs}>{content}</w:fldSimple>"


def complex_field(content=None, command="AUTHOR", separator=True, attrs=""):
    middle = (
        char("separate") + (literal("Cached") if content is None else content) if separator else ""
    )
    return char("begin", attrs) + instr(command) + middle + char("end")


def build(raw, **kw):
    return api().build_field_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest(), **kw
    )


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
@pytest.mark.parametrize("kind", ["simple", "complex"])
def test_stored_result_not_command_with_original_piece_paths(strict, encoding, kind):
    field = simple() if kind == "simple" else run(complex_field())
    raw, xml = source(
        "<w:p>" + run(literal("Before ")) + field + run(literal(" after")) + "</w:p>",
        strict=strict,
        encoding=encoding,
    )
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.analysis_text == "Before Cached after"
    assert s.references == () and s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    f = s.fragments[0]
    assert len(f.pieces) == 3
    root = ET.fromstring(xml)
    from test_docx_move_catalog import resolve

    assert (
        "".join(resolve(root, x.anchor).text[x.source_start : x.source_end] for x in f.pieces)
        == f.text
    )
    assert "AUTHOR" not in repr(s) + s.analysis_text and sha256(raw).hexdigest() == s.source_sha256
    assert ("metadata", "cached_field_result") in codes(s)


def test_nested_fields_in_outer_code_do_not_leak_their_cached_results():
    inner = complex_field(literal("DO NOT READ"), command="FILENAME")
    body = p(
        char("begin")
        + instr("IF ")
        + inner
        + instr(" = 1 ")
        + char("separate")
        + literal("Outer")
        + char("end")
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Outer"
    assert ("excluded", "field_code_content") in codes(s)


def test_nested_simple_and_complex_results_preserve_literal_text_order():
    body = (
        "<w:p>"
        + simple(run(literal("A")) + simple(run(complex_field(literal("B")))) + run(literal("C")))
        + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "ABC"


def test_instruction_element_outside_complex_code_is_literal_source_text():
    body = p(instr("Ordinary ") + complex_field(instr("Literal cached")) + instr(" tail"))
    raw = source(body)[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Ordinary Literal cached tail"
    assert all(piece.kind == "text" for piece in s.fragments[0].pieces)
    f = s.fragments[0]
    m = api().map_field_span(
        raw, s, fragment_id=f.fragment_id, start=0, end=len(f.text), quote=f.text
    )
    assert len(m.slices) == 3


def test_complex_field_crosses_paragraphs_in_same_body_flow():
    body = p(char("begin") + instr("TOC") + char("separate") + literal("Heading"))
    body += p(literal("Second") + char("end"))
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Heading\n\nSecond" and len(s.fragments) == 2
    assert s.fragments[0].flow_anchor == s.fragments[1].flow_anchor


def test_closed_code_only_and_empty_simple_fields_add_no_fabricated_text():
    body = (
        "<w:p>"
        + run(literal("A") + complex_field(separator=False))
        + simple("")
        + run(literal("B"))
        + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "AB"
    assert ("metadata", "field_without_result") in codes(s)


def test_hidden_field_markers_still_control_code_but_cached_run_visibility_applies():
    def hidden(content):
        return "<w:r><w:rPr><w:vanish/></w:rPr>" + content + "</w:r>"

    body = "<w:p>" + hidden(char("begin")) + run(instr("AUTHOR")) + hidden(char("separate"))
    body += run(literal("Visible")) + hidden(literal("HIDDEN")) + hidden(char("end")) + "</w:p>"
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Visible"


def test_note_references_in_code_do_not_activate_missing_notes_but_result_references_do():
    body = p(
        char("begin")
        + instr("IF ")
        + ref("999")
        + char("separate")
        + literal("Result")
        + ref()
        + char("end")
    )
    s = build(notes_fixture(body)[0])
    assert s.complete and s.analysis_text == "Result\n\nFoot 🧪" and len(s.references) == 1


def test_fields_in_table_and_note_use_each_original_flow():
    body = table(row(cell(p(complex_field(literal("Cell")) + ref()))), 1)
    raw, _, _ = notes_fixture(
        body, foot=note(content="<w:p>" + simple(run(literal("Note"))) + "</w:p>")
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "Cell\n\nNote"
    assert s.fragments[0].flow_anchor != s.fragments[0].story_anchor
    assert s.fragments[1].story_anchor.part_name == "custom/Foot.xml"


def test_field_result_in_header_does_not_depend_on_main_field_stack():
    links = [{"Id": "H", "Type": R + "header", "Target": "H.xml"}]
    extras = {"custom/H.xml": story_xml(p(complex_field(literal("Header"))))}
    raw = source(
        paragraph("Body") + section(reference()),
        links=links,
        extra_parts=extras,
        extra_types={"custom/H.xml": BASE + "header+xml"},
    )[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Body\n\nHeader"


@pytest.mark.parametrize(
    "content",
    [
        char("end"),
        char("separate"),
        char("begin") + instr(),
        char("begin") + char("separate") + char("separate") + char("end"),
        char("begin") + char("end") + char("end"),
        char("start"),
    ],
)
def test_malformed_complex_field_is_atomic_instead_of_guessing_word_fallback(content):
    s = build(source(paragraph("Prefix") + p(content))[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.references == ()


@pytest.mark.parametrize(
    "content",
    [
        "<w:p>" + simple(run(char("begin") + instr("AUTHOR"))) + run(char("end")) + "</w:p>",
        table(
            row(
                cell(p(char("begin") + instr()))
                + cell(p(char("separate") + literal("Text") + char("end")))
            ),
            2,
        ),
        p(char("begin") + instr())
        + table(row(cell("<w:p/>")), 1)
        + p(char("separate") + literal("Text") + char("end")),
    ],
)
def test_fields_cannot_cross_simple_wrapper_or_cell_boundaries(content):
    s = build(source(content)[0])
    assert not s.complete and s.fragments == s.references == ()


@pytest.mark.parametrize(
    "field",
    [
        simple(attrs=' w:dirty="1"'),
        run(complex_field(attrs=' w:dirty="true"')),
        simple(attrs=' w:other="x"'),
        simple(attrs=' w:fldLock="maybe"'),
        run(char("begin") + '<w:instrText w:extra="1">AUTHOR</w:instrText>' + char("end")),
        run('<w:fldChar w:fldCharType="begin"><w:ffData/></w:fldChar>' + char("end")),
    ],
)
def test_invalidated_cache_or_unproved_markup_never_becomes_success(field):
    s = build(source("<w:p>" + field + "</w:p>")[0])
    assert not s.complete and s.fragments == s.references == ()


@pytest.mark.parametrize(
    "command", ["DDE shell SYSTEM", 'INCLUDETEXT "https://invalid.example"', "PAGE", "TOC"]
)
def test_instruction_is_opaque_and_never_executed(command):
    s = build(
        source("<w:p>" + simple(command=command, attrs=' w:fldLock="1" w:dirty="0"') + "</w:p>")[0]
    )
    assert s.complete and s.analysis_text == "Cached"
