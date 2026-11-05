"""Direct single-level numbering is preserved separately from original literal spans."""

import io
import zipfile
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_table_catalog import cell, row, table
from test_docx_visible_controls import control
from test_docx_visible_fields import char, instr
from test_docx_visible_inline_images import IMAGE, drawing, png
from test_docx_visible_main import DOC, R, canonical, codes, payload, rehash
from test_docx_visible_plain_controls import plain, run
from test_docx_visible_unlisted import DEFS, LEVEL, selected, source

from ara.docx_package.creation import NewParagraph, create_docx

PROFILE = "docx-analysis/final-visible-direct-lists-v1"


def api():
    return import_module("ara.docx_analysis.visible_lists")


def build(raw, **kw):
    return api().build_list_snapshot(
        raw,
        **(dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()) | kw),
    )


def paragraph(text="Item", number=1, level=0, atoms=None):
    props = ('<w:ilvl w:val="' + str(level) + '"/>') if level is not None else ""
    props += '<w:numId w:val="' + str(number) + '"/>'
    return (
        "<w:p><w:pPr><w:numPr>" + props + "</w:numPr></w:pPr>" + run(text, atoms=atoms) + "</w:p>"
    )


def error(code, call):
    with pytest.raises(api().VisibleViewError) as e:
        call()
    assert e.value.code == code


def original(raw, parts, s):
    requests = tuple(
        api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text) for f in s.fragments
    )
    for f, mapped in zip(s.fragments, api().map_list_spans(raw, s, requests=requests), strict=True):
        text = []
        for item in mapped.slices:
            node = resolve(ET.fromstring(parts[item.anchor.part_name]), item.anchor)
            value = node.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            text.append(value[item.start : item.end])
        assert "".join(text) == f.text
    for item in s.lists:
        for key, tag in [
            ("paragraph_anchor", "p"),
            ("properties_anchor", "numPr"),
            ("definition_anchor", "lvl"),
            ("instance_anchor", "num"),
        ]:
            a = getattr(item, key)
            assert resolve(ET.fromstring(parts[a.part_name]), a).tag.endswith("}" + tag)
        if item.start_override_anchor is not None:
            a = item.start_override_anchor
            assert resolve(ET.fromstring(parts[a.part_name]), a).tag.endswith("}startOverride")


def test_actual_aira_template_list_groups_keep_labels_and_exact_literal_text():
    content = (
        ("Title", "heading1"),
        ("One😀", "numbered"),
        ("Two", "numbered"),
        ("Text", "body"),
        ("Restart", "numbered"),
        ("Bullet", "bullet"),
        ("Again", "numbered"),
    )
    raw = create_docx(tuple(NewParagraph(text, style) for text, style in content))
    before = sha256(raw).hexdigest()
    s = build(raw)
    assert s.complete and s.profile == PROFILE and type(s) is api().ListSnapshot
    assert [f.text for f in s.fragments] == [text for text, _ in content]
    assert [(x.format, x.ordinal, x.label, x.suffix) for x in s.lists] == [
        ("decimal", 1, "1.", "tab"),
        ("decimal", 2, "2.", "tab"),
        ("decimal", 1, "1.", "tab"),
        ("bullet", 1, "•", "tab"),
        ("decimal", 1, "1.", "tab"),
    ]
    assert all(x.level == 0 and type(x.num_id) is int for x in s.lists)
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and s == build(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        original(raw, {name: z.read(name) for name in z.namelist()}, s)
    assert sha256(raw).hexdigest() == before


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_main_sequence_continues_across_unlisted_paragraphs_and_table_cells(strict, encoding):
    body = (
        paragraph("A")
        + "<w:p>"
        + run("Gap")
        + "</w:p>"
        + table(row(cell(paragraph("B"))) + row(cell(paragraph("C"))), 1)
        + paragraph("D")
    )
    raw, parts = source(body, strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and [x.label for x in s.lists] == ["1.", "2.", "3.", "4."]
    assert [f.text for f in s.fragments] == ["A", "Gap", "B", "C", "D"]
    original(raw, parts, s)


@pytest.mark.parametrize("wrapper", ["rich", "plain", "selected"])
def test_list_paragraph_ownership_survives_original_content_wrappers(wrapper):
    body = paragraph("A😀\t")
    body = (
        control(body)
        if wrapper == "rich"
        else plain(body)
        if wrapper == "plain"
        else selected(body)
    )
    raw, parts = source(body)
    s = build(raw)
    assert s.complete and len(s.lists) == 1 and s.lists[0].label == "1."
    assert s.lists[0].fragment_ids == (s.fragments[0].fragment_id,)
    original(raw, parts, s)


def test_interleaved_instances_restart_independently_and_override_start_is_not_renewed():
    defs = (
        DEFS + '<w:num w:numId="2"><w:abstractNumId w:val="0"/>'
        '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="7"/></w:lvlOverride></w:num>'
    )
    raw, parts = source(
        paragraph("A") + paragraph("B", 2) + paragraph("C") + paragraph("D", 2), defs
    )
    s = build(raw)
    assert s.complete and [(x.num_id, x.ordinal, x.label) for x in s.lists] == [
        (1, 1, "1."),
        (2, 7, "7."),
        (1, 2, "2."),
        (2, 8, "8."),
    ]
    assert s.lists[0].start_override_anchor is None and s.lists[1].start_override_anchor is not None
    original(raw, parts, s)


@pytest.mark.parametrize("start", [None, 0, 9])
@pytest.mark.parametrize("suffix", [None, "tab", "space", "nothing"])
def test_normative_defaults_and_explicit_start_suffix_are_preserved(start, suffix):
    defs = DEFS.replace(
        '<w:start w:val="1"/>', "" if start is None else '<w:start w:val="' + str(start) + '"/>'
    )
    defs = defs.replace('<w:numFmt w:val="decimal"/>', "")
    if suffix is not None:
        defs = defs.replace("<w:lvlText", '<w:suff w:val="' + suffix + '"/><w:lvlText')
    raw, _ = source(paragraph("Text"), defs)
    s = build(raw)
    assert s.complete and s.lists[0].ordinal == (0 if start is None else start)
    assert s.lists[0].label == str(0 if start is None else start) + "."
    assert s.lists[0].suffix == (suffix or "tab") and s.analysis_text == "Text"


def test_empty_and_hidden_literal_paragraphs_still_have_numbering_evidence():
    body = (
        paragraph("")
        + paragraph(atoms="<w:rPr><w:vanish/></w:rPr><w:t>Hidden</w:t>")
        + paragraph("Visible")
    )
    raw, parts = source(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "Visible"
    assert [x.label for x in s.lists] == ["1.", "2.", "3."]
    assert s.lists[0].fragment_ids == s.lists[1].fragment_ids == ()
    assert s.lists[2].fragment_ids == (s.fragments[0].fragment_id,)
    assert "Hidden" not in repr(s)
    original(raw, parts, s)


def test_images_split_literal_text_without_duplicating_the_list_marker():
    raw, parts = source(
        paragraph(atoms="<w:t>Before</w:t>" + drawing() + "<w:t>After</w:t>"),
        extra_parts={IMAGE: png()},
        extra_types={IMAGE: "image/png"},
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "I", "Type": R + "image", "Target": "picture.bin"},
        ],
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Before", "After"]
    assert len(s.lists) == 1 and s.lists[0].fragment_ids == tuple(
        f.fragment_id for f in s.fragments
    )
    original(raw, parts, s)


def test_zero_removes_numbering_without_a_definition_part_or_synthetic_marker():
    from test_docx_visible_main import source as no_numbering_source

    raw, _ = no_numbering_source(paragraph("Unlisted", number=0, level=None))
    s = build(raw)
    assert s.complete and s.analysis_text == "Unlisted" and s.lists == ()
    assert ("metadata", "numbering_removed") in codes(s)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.replace('w:val="decimal"', 'w:val="upperRoman"'),
        lambda d: d.replace('w:val="%1."', 'w:val="%2."'),
        lambda d: d.replace('w:val="%1."', 'w:val="%10."'),
        lambda d: d.replace("<w:lvlText", "<w:isLgl/><w:lvlText"),
        lambda d: d.replace("<w:lvlText", '<w:lvlRestart w:val="1"/><w:lvlText'),
        lambda d: d.replace('<w:lvlText w:val="%1."/>', '<w:lvlText w:val="%1." w:null="1"/>'),
        lambda d: d.replace("</w:lvl>", "<w:rPr><w:vanish/></w:rPr></w:lvl>"),
        lambda d: d.replace(LEVEL, '<w:multiLevelType w:val="multilevel"/>' + LEVEL),
        lambda d: d.replace(
            "</w:abstractNum>", LEVEL.replace('ilvl="0"', 'ilvl="1"') + "</w:abstractNum>"
        ),
        lambda d: d.replace(
            "</w:num>", '<w:lvlOverride w:ilvl="0">' + LEVEL + "</w:lvlOverride></w:num>"
        ),
    ],
)
def test_unsupported_active_semantics_never_disappear_as_unused(change):
    s = build(source(paragraph("Private"), change(DEFS))[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.lists == s.references == ()
    assert ("excluded", "unused_numbering_definition") not in codes(s)


@pytest.mark.parametrize(
    "body",
    [
        paragraph("Private", level=None),
        paragraph("Private", level=1),
        paragraph("Private", number=8),
        paragraph("Private").replace(
            '<w:ilvl w:val="0"/>', '<w:ilvl w:val="0"/><w:ilvl w:val="0"/>'
        ),
        paragraph("Private").replace("</w:numPr>", '<w:numberingChange w:id="1"/></w:numPr>'),
    ],
)
def test_direct_numbering_properties_are_closed_and_resolved(body):
    s = build(source(body)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.lists == ()


def test_single_paragraph_field_result_works_but_cross_paragraph_field_boundary_gates():
    data = paragraph(
        atoms=char("begin")
        + instr("PRIVATE")
        + char("separate")
        + "<w:t>Result</w:t>"
        + char("end")
    )
    raw, parts = source(data)
    s = build(raw)
    assert s.complete and s.analysis_text == "Result" and s.lists[0].label == "1."
    original(raw, parts, s)
    body = paragraph(atoms=char("begin") + instr("PRIVATE")) + paragraph(
        atoms=char("separate") + "<w:t>Result</w:t>" + char("end")
    )
    s = build(source(body)[0])
    assert not s.complete and s.fragments == s.lists == ()
    assert any(c.code == "unsupported_list_field_boundary" for c in s.coverage)


def test_old_profiles_cannot_accept_new_or_rehashed_list_evidence():
    from ara.docx_analysis.visible_unlisted import build_unlisted_snapshot, map_unlisted_spans

    raw, _ = source(paragraph("Literal"))
    old = build_unlisted_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not old.complete
    s = build(raw)
    error("invalid_snapshot", lambda: map_unlisted_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_list_spans(raw, old, requests=()))
    for item in (
        replace(s.lists[0], label="999."),
        replace(s.lists[0], ordinal=9),
        replace(s.lists[0], fragment_ids=()),
    ):
        error(
            "invalid_snapshot",
            lambda item=item: api().map_list_spans(
                raw, rehash(replace(s, lists=(item,))), requests=()
            ),
        )
