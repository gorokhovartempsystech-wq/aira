"""Plain controls preserve saved text, uniform current formatting and source addresses."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_compatibility_contexts import fixture
from test_docx_move_catalog import resolve
from test_docx_note_catalog import note
from test_docx_retained_tables import marker
from test_docx_section_catalog import reference, section
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visibility_styles import style
from test_docx_visible_compatibility import selected
from test_docx_visible_controls import control
from test_docx_visible_fields import char, instr
from test_docx_visible_main import DOC, canonical, codes, payload, rehash
from test_docx_visible_notes import p, ref

PROFILE = "docx-analysis/final-visible-plain-controls-v1"


def api():
    return import_module("ara.docx_analysis.visible_plain_controls")


def build(raw, **kw):
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    return api().build_plain_control_snapshot(raw, **(identity | kw))


def plain(content, *, attrs="", props=""):
    return control(content, props + f"<w:text{attrs}/>")


def run(text="Text", props="", atoms=None):
    properties = "<w:rPr>" + props + "</w:rPr>" if props else ""
    return "<w:r>" + properties + (f"<w:t>{text}</w:t>" if atoms is None else atoms) + "</w:r>"


def request(f):
    return api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


def original(raw, parts, s):
    results = api().map_plain_control_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    trees = {name: ET.fromstring(xml) for name, xml in parts.items()}
    for f, result in zip(s.fragments, results, strict=True):
        text = []
        assert resolve(trees[f.paragraph_anchor.part_name], f.paragraph_anchor).tag.endswith("}p")
        for item in result.slices:
            node = resolve(trees[item.anchor.part_name], item.anchor)
            value = node.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            text.append(value[item.start : item.end])
            assert item.anchor.source_sha256 == s.source_sha256
        assert "".join(text) == f.text


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
@pytest.mark.parametrize("role", ["inline", "block", "cell", "nested_rich"])
def test_plain_roles_use_selected_original_nodes_and_real_cell_flow(strict, encoding, role):
    inline = plain(selected(run("Я😀")))
    body = "<w:p>" + inline + "</w:p>"
    if role in ("block", "nested_rich"):
        body = plain(selected(paragraph("Я😀")))
        if role == "nested_rich":
            body = control(selected(body))
    elif role == "cell":
        body = table(row(selected(plain(cell(paragraph("Я😀"))))), 1)
    raw, parts = fixture(selected(body), strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.analysis_text == "Я😀" and s.profile == PROFILE
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and s == build(raw)
    assert {
        ("metadata", "plain_text_control"),
        ("metadata", "plain_control_format_proven"),
    } <= codes(s)
    if role == "cell":
        f = s.fragments[0]
        assert resolve(ET.fromstring(parts[f.flow_anchor.part_name]), f.flow_anchor).tag.endswith(
            "}tc"
        )
    original(raw, parts, s)


@pytest.mark.parametrize("flag", [None, "false", "0", "off", "true", "1", "on"])
def test_saved_soft_breaks_are_preserved_even_when_new_breaks_are_disabled(flag):
    attrs = "" if flag is None else f' w:multiLine="{flag}"'
    content = run(props="<w:b/>", atoms="<w:t>A</w:t><w:br/>")
    content += run(props="<w:b/>", atoms="<w:t>B</w:t><w:cr/><w:t>C</w:t><w:tab/><w:t>😀</w:t>")
    raw, parts = fixture("<w:p>" + plain(selected(content), attrs=attrs) + "</w:p>")
    s = build(raw)
    assert s.complete and s.analysis_text == "A\nB\nC\t😀" and len(s.runs) == 2
    original(raw, parts, s)


def test_current_formatting_ignores_history_but_not_current_style_or_visibility():
    hist = '<w:rPrChange w:id="3"><w:rPr><w:vanish/></w:rPr></w:rPrChange>'
    props = '<w:rStyle w:val="Visible"/><w:b/>'
    content = (
        run("A", props + hist)
        + '<w:ins w:id="1">'
        + run("B", "<w:b/>" + '<w:rStyle w:val="Visible"/>')
        + "</w:ins>"
    )
    content += '<w:del w:id="2"><w:r><w:delText>OLD</w:delText></w:r></w:del>'
    content += '<w:commentRangeStart w:id="1"/><w:commentRangeEnd w:id="1"/>'
    raw, parts = fixture(
        "<w:p>" + plain(content) + "</w:p>", styles=style("Visible", kind="character")
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "AB"
    assert {
        ("excluded", "historical_properties"),
        ("excluded", "deleted_content"),
        ("excluded", "comments_policy"),
    } <= codes(s)
    original(raw, parts, s)


def test_input_and_end_properties_are_not_blanket_overrides_of_saved_plain_runs():
    content = run("Visible") + run(" too")
    body = control(
        content,
        "<w:rPr><w:vanish/></w:rPr><w:text/>",
        "<w:sdtEndPr><w:rPr><w:vanish/></w:rPr></w:sdtEndPr>",
    )
    s = build(fixture("<w:p>" + body + "</w:p>")[0])
    assert s.complete and s.analysis_text == "Visible too"
    hidden = plain(run("HIDDEN", "<w:vanish/>") + run(" ALSO", "<w:vanish/>"))
    s = build(fixture("<w:p>" + hidden + "</w:p>")[0])
    assert s.complete and s.analysis_text == "" and s.fragments == ()


def test_plain_controls_in_headers_and_referenced_notes_keep_story_ownership():
    body = p(ref()) + section(reference("H"))
    raw, parts = fixture(
        body,
        header=plain(paragraph("Header")),
        foot=selected(note("2", content=plain(paragraph("Foot")))),
    )
    s = build(raw)
    assert (
        s.complete
        and [f.text for f in s.fragments] == ["Header", "Foot"]
        and len(s.references) == 1
    )
    original(raw, parts, s)


@pytest.mark.parametrize("content", [None, "", "<w:p/>"])
def test_empty_plain_block_controls_do_not_invent_text(content):
    raw = fixture(plain(content))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "" and s.fragments == ()
    assert api().map_plain_control_spans(raw, s, requests=()) == ()


def test_plain_cell_uses_proven_deletion_before_ignoring_old_payload():
    deleted = plain(cell("<w:p><w:unknown/></w:p>", marker("cellDel")))
    raw, parts = fixture(table(row(selected(deleted) + cell(paragraph("Kept"))), 1))
    s = build(raw)
    assert s.complete and s.analysis_text == "Kept"
    original(raw, parts, s)


@pytest.mark.parametrize(
    "a,b", [("", "<w:b/>"), ("<w:vanish/>", ""), ('<w:rStyle w:val="A"/>', '<w:rStyle w:val="B"/>')]
)
def test_unproved_uniformity_never_returns_a_partial_plain_result(a, b):
    styles = style("A", kind="character") + style("B", kind="character")
    raw = fixture("<w:p>" + plain(run("One", a) + run("Two", b)) + "</w:p>", styles=styles)[0]
    s = build(raw)
    assert not s.complete and s.analysis_text == "" and s.fragments == s.runs == s.references == ()
    assert ("blocked", "unsupported_plain_control_formatting") in codes(s)


@pytest.mark.parametrize(
    "body",
    [
        plain(paragraph("One") + paragraph("Two")),
        plain(table()),
        table(plain(row()), 2),
        table(plain(""), 1),
        table(row(plain(cell(paragraph("A") + paragraph("B")))), 1),
        "<w:p>" + plain(control(run("Nested"))) + "</w:p>",
        "<w:p>" + plain(run(atoms="<w:drawing/>", props="<w:vanish/>")) + "</w:p>",
        "<w:p>" + plain(run(atoms='<w:br w:type="page"/>')) + "</w:p>",
        "<w:p>" + plain(run("A"), attrs=' w:multiLine="wrong"') + "</w:p>",
        "<w:p>" + plain(run("A"), props="<w:richText/>") + "</w:p>",
        "<w:p>" + plain(run("A"), props="<w:showingPlcHdr/>") + "</w:p>",
        "<w:p>" + plain(run(atoms=ref())) + "</w:p>",
    ],
)
def test_unsupported_plain_shape_or_content_is_atomic(body):
    raw = fixture(paragraph("Before") + selected(body))[0]
    s = build(raw)
    assert not s.complete and s.analysis_text == ""
    assert s.fragments == s.runs == s.paragraphs == s.references == ()
    assert any(c.status == "blocked" for c in s.coverage)
    assert api().map_plain_control_spans(raw, s, requests=()) == ()


def test_even_empty_plain_control_is_a_field_boundary():
    body = "<w:p><w:r>" + char("begin") + instr() + "</w:r>" + plain("")
    body += "<w:r>" + char("separate") + "<w:t>Bad</w:t>" + char("end") + "</w:r></w:p>"
    s = build(fixture(body)[0])
    assert not s.complete and s.fragments == () and s.analysis_text == ""


def test_old_profiles_remain_closed_and_rehashed_fake_sources_do_not_map():
    old = import_module("ara.docx_analysis.visible_compatibility")
    raw = fixture("<w:p>" + plain(run("Text")) + "</w:p>")[0]
    kw = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    previous, current = old.build_compatibility_snapshot(raw, **kw), build(raw)
    assert not previous.complete and current.complete
    assert old.build_compatibility_snapshot(raw, **kw) == previous
    error("invalid_snapshot", lambda: old.map_compatibility_spans(raw, current, requests=()))
    error("invalid_snapshot", lambda: api().map_plain_control_spans(raw, previous, requests=()))
    fake = rehash(replace(current, analysis_text="Fake", coverage=()))
    error("invalid_snapshot", lambda: api().map_plain_control_spans(raw, fake, requests=()))
