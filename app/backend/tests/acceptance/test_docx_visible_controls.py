"""Saved unbound rich controls preserve source ownership and existing visibility."""

from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_note_catalog import note
from test_docx_section_catalog import BASE, reference, section
from test_docx_table_catalog import cell, row, table
from test_docx_visible_fields import char, complex_field, instr, run, simple
from test_docx_visible_main import DOC, R, canonical, codes, payload, source
from test_docx_visible_notes import fixture, literal, p, ref
from test_docx_visible_stories import story_xml

PROFILE = "docx-analysis/final-visible-rich-controls-v1"


def api():
    return import_module("ara.docx_analysis.visible_controls")


def control(content=None, props=None, end=""):
    properties = "" if props is None else "<w:sdtPr>" + props + "</w:sdtPr>"
    contents = "" if content is None else "<w:sdtContent>" + content + "</w:sdtContent>"
    return "<w:sdt>" + properties + end + contents + "</w:sdt>"


def build(raw, **kw):
    return api().build_control_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest(), **kw
    )


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


def blocked(body):
    s = build(source(body)[0])
    assert not s.complete and s.analysis_text == ""
    assert s.fragments == s.references == s.paragraphs == s.runs == ()
    return s


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
@pytest.mark.parametrize("props", [None, "", "<w:richText/>"])
def test_block_and_inline_controls_keep_original_text_paths(strict, encoding, props):
    inline = control(run(literal("Inside")), props)
    body = p(literal("First")) + control(
        "<w:p>" + run(literal("Before ")) + inline + "</w:p>", props
    )
    raw, xml = source(body, strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.analysis_text == "First\n\nBefore Inside"
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    assert len(s.paragraphs) == len(s.fragments) == 2
    tree = ET.fromstring(xml)
    for f in s.fragments:
        assert (
            "".join(resolve(tree, a.anchor).text[a.source_start : a.source_end] for a in f.pieces)
            == f.text
        )
    assert s.fragments[0].flow_anchor == s.fragments[1].flow_anchor
    assert ("metadata", "rich_text_control") in codes(s)
    assert sha256(raw).hexdigest() == s.source_sha256


@pytest.mark.parametrize("content", [None, ""])
def test_empty_or_absent_control_content_does_not_invent_text(content):
    s = build(source(control(content) + "<w:p>" + control(content) + "</w:p>")[0])
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert len(s.paragraphs) == 1 and s.runs == ()
    assert ("metadata", "empty_control") in codes(s)


def test_nested_block_and_inline_controls_keep_order_and_real_paragraphs():
    body = control(
        control(p(literal("One"))) + "<w:p>" + control(control(run(literal("Two")))) + "</w:p>"
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "One\n\nTwo" and len(s.paragraphs) == 2
    assert len({f.paragraph_anchor for f in s.fragments}) == 2


def test_control_metadata_and_new_input_properties_do_not_hide_saved_runs():
    props = (
        '<w:rPr><w:rStyle w:val="MissingFutureStyle"/><w:vanish/></w:rPr>'
        '<w:alias w:val="INTERNAL_ALIAS"/><w:tag w:val="INTERNAL_TAG"/>'
        '<w:id w:val="-12"/><w:lock w:val="sdtContentLocked"/>'
        '<w:placeholder><w:docPart w:val="INTERNAL_PLACEHOLDER"/></w:placeholder>'
        '<w:temporary w:val="on"/><w:showingPlcHdr w:val="off"/>'
        '<w:label w:val="+3"/><w:tabIndex w:val="0"/><w:richText/>'
    )
    end = "<w:sdtEndPr><w:rPr><w:vanish/></w:rPr><w:rPr><w:b/></w:rPr></w:sdtEndPr>"
    s = build(source(control(p(literal("Saved")), props, end))[0])
    assert s.complete and s.analysis_text == "Saved"
    assert "INTERNAL" not in repr(s) and "MissingFutureStyle" not in repr(s)


def test_child_direct_hidden_and_final_deleted_content_keep_existing_rules():
    hidden = "<w:r><w:rPr><w:vanish/></w:rPr>" + literal("Hidden") + "</w:r>"
    removed = '<w:del w:id="1">' + control(run(literal("Removed")), "<w:date/>") + "</w:del>"
    kept = '<w:ins w:id="2">' + control(run(literal("Kept"))) + "</w:ins>"
    s = build(source("<w:p>" + control(hidden + removed + kept) + "</w:p>")[0])
    assert s.complete and s.analysis_text == "Kept"


def test_inline_control_inside_real_cell_keeps_cell_flow():
    body = table(row(cell("<w:p>" + control(run(literal("Cell"))) + "</w:p>")), columns=1)
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Cell"
    assert s.fragments[0].flow_anchor.path == (0, 0, 1, 0)


def test_controls_in_header_and_active_note_keep_story_ownership():
    body = control(p(ref())) + section(reference())
    raw = fixture(
        body,
        foot=note(content=control(p("<w:footnoteRef/>" + literal("Note")))),
        links=[
            {"Id": "H", "Type": R + "header", "Target": "H.xml"},
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
        extras={"custom/H.xml": story_xml(control(p(literal("Header"))))},
        types={"custom/H.xml": BASE + "header+xml"},
    )[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Header\n\nNote" and len(s.references) == 1
    assert [f.story_anchor.part_name for f in s.fragments] == ["custom/H.xml", "custom/Foot.xml"]
    assert s.references[0].target_anchor == s.fragments[1].story_anchor


def test_closed_fields_inside_control_and_separate_fields_outside_work():
    body = "<w:p>" + simple() + control(simple(run(complex_field(literal("Inside"))))) + "</w:p>"
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "CachedInside"
    body = control(
        p(char("begin") + instr() + char("separate") + literal("A")) + p(literal("B") + char("end"))
    )
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "A\n\nB"


@pytest.mark.parametrize(
    "props",
    [
        '<w:dataBinding w:storeItemID="fake" w:xpath="/secret"/>',
        "<w:showingPlcHdr/>",
        "<w:text/>",
        "<w:date/>",
        "<w:group/>",
        "<w:richText/><w:richText/>",
        "<w:alias/>",
        '<w:id w:val="NaN"/>',
        '<w:tabIndex w:val="-1"/>',
        '<w:lock w:val="madeUp"/>',
        '<w:temporary w:val="TRUE"/>',
        '<w:showingPlcHdr w:val="2"/>',
        '<w:placeholder><w:docPart w:val="A"/><w:docPart w:val="B"/></w:placeholder>',
        '<w:alias w:val="A">Payload</w:alias>',
        '<w:richText w:val="true"/>',
        "<w:unknown/>",
        "<w:rPr><w:unknown/></w:rPr>",
    ],
)
def test_unsupported_control_properties_are_atomic(props):
    blocked(p(literal("Prefix")) + control(p(literal("Must not leak")), props))


@pytest.mark.parametrize(
    "body",
    [
        '<w:sdt w:id="1"><w:sdtContent/></w:sdt>',
        "<w:sdt><w:sdtContent/><w:sdtPr/></w:sdt>",
        "<w:sdt><w:sdtContent/><w:sdtContent/></w:sdt>",
        "<w:sdt>Text<w:sdtContent/></w:sdt>",
        '<w:sdt><w:sdtContent w:id="1"/></w:sdt>',
        "<w:sdt><w:sdtEndPr><w:t>Unknown</w:t></w:sdtEndPr></w:sdt>",
        control(run(literal("Run outside paragraph"))),
        "<w:p>" + control(p(literal("Paragraph inside inline"))) + "</w:p>",
        control(table(row(cell(p(literal("Wrapped table")))), columns=1)),
        table(row(cell(control(p(literal("Cell block control"))))), columns=1),
        control("<w:p><w:pPr>" + section() + "</w:pPr>" + run(literal("Section")) + "</w:p>"),
    ],
)
def test_wrong_wrapper_or_context_does_not_produce_partial_result(body):
    blocked(p(literal("Prefix")) + body)


@pytest.mark.parametrize(
    "body",
    [
        "<w:p>"
        + run(char("begin") + instr() + char("separate"))
        + control(run(literal("Inside")))
        + run(char("end"))
        + "</w:p>",
        "<w:p>"
        + control(run(char("begin") + instr() + char("separate") + literal("Inside")))
        + run(char("end"))
        + "</w:p>",
        "<w:p>" + simple(control(run(literal("Nested")))) + "</w:p>",
        control(
            p(char("begin") + instr())
            + control(p(char("separate") + literal("Nested") + char("end")))
        ),
    ],
)
def test_field_crossing_a_control_boundary_is_explicitly_blocked(body):
    blocked(body)


def test_hidden_unknown_inside_control_is_not_skipped():
    unknown = "<w:r><w:rPr><w:vanish/></w:rPr><w:drawing/></w:r>"
    blocked("<w:p>" + control(unknown) + "</w:p>")


def test_existing_child_style_visibility_is_used_inside_rich_controls():
    from test_docx_visible_main import style

    styles = style("Hidden", "<w:rPr><w:vanish/></w:rPr>", kind="character")
    hidden = '<w:r><w:rPr><w:rStyle w:val="Hidden"/></w:rPr>' + literal("Hidden") + "</w:r>"
    raw = source("<w:p>" + control(hidden + run(literal("Shown"))) + "</w:p>", styles)[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Shown"
