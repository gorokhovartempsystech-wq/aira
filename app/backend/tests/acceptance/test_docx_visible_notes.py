"""Visible note content keeps generated markers separate from literal requirements."""

from dataclasses import FrozenInstanceError
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from docx_package_fixtures import relationships_xml
from test_docx_current_tables import history
from test_docx_grid_tables import gridless
from test_docx_move_catalog import group, resolve, run
from test_docx_note_catalog import note
from test_docx_retained_tables import marker
from test_docx_section_catalog import BASE, reference, section
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_main import DOC, SR, R, S, W, canonical, codes, payload, source, style
from test_docx_visible_stories import story_xml
from test_docx_visible_styled_tables import table_style

PROFILE = "docx-analysis/final-visible-note-stories-v1"


def api():
    return import_module("ara.docx_analysis.visible_notes")


def ref(identity="2", kind="footnote", attrs=""):
    return f'<w:{kind}Reference w:id="{identity}"{attrs}/>'


def p(content):
    return "<w:p><w:r>" + content + "</w:r></w:p>"


def literal(text):
    return "<w:t>" + text + "</w:t>"


def note_xml(content, kind="footnote", *, strict=False, encoding="utf-8"):
    ns, rel = (S, SR) if strict else (W, R)
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:{kind}s xmlns:w="{ns}" xmlns:r="{rel[:-1]}">{content}</w:{kind}s>'
    ).encode(encoding)


def fixture(
    body=None,
    foot=None,
    end=None,
    *,
    strict=False,
    encoding="utf-8",
    styles=None,
    links=None,
    extras=None,
    types=None,
    foot_links=(),
):
    foot = note("2", content=p("<w:footnoteRef/>" + literal("Foot 🧪"))) if foot is None else foot
    end = (
        note("2", kind="endnote", content=p("<w:endnoteRef/>" + literal("End")))
        if end is None
        else end
    )
    parts = {
        "custom/Foot.xml": note_xml(foot, strict=strict, encoding=encoding),
        "custom/End.xml": note_xml(end, "endnote", strict=strict, encoding=encoding),
    }
    ctypes = {"custom/Foot.xml": BASE + "footnotes+xml", "custom/End.xml": BASE + "endnotes+xml"}
    if foot_links:
        parts["custom/_rels/Foot.xml.rels"] = relationships_xml(foot_links, encoding=encoding)
    parts.update(extras or {})
    ctypes.update(types or {})
    rel = SR if strict else R
    if links is None:
        links = [
            {"Id": "NoteF", "Type": rel + "footnotes", "Target": "Foot.xml"},
            {"Id": "NoteE", "Type": rel + "endnotes", "Target": "End.xml"},
        ]
    body = p(literal("Before") + ref() + literal("After")) if body is None else body
    raw, xml = source(
        body,
        styles,
        strict=strict,
        encoding=encoding,
        extra_parts=parts,
        extra_types=ctypes,
        links=links,
    )
    return raw, xml, parts


def build(raw, **kw):
    return api().build_note_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest(), **kw
    )


def request(fragment, start=0, end=None):
    end = len(fragment.text) if end is None else end
    return api().VisibleSpanRequest(fragment.fragment_id, start, end, fragment.text[start:end])


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_generated_marker_segments_original_note_paths_and_source_bound_links(strict, encoding):
    raw, xml, parts = fixture(strict=strict, encoding=encoding)
    s = build(raw)
    assert type(s) is api().NoteSnapshot and s.complete and s.profile == PROFILE
    assert s.analysis_text == "Before\n\nAfter\n\nFoot 🧪" and s.main_part == "custom/Main.xml"
    assert len(s.references) == 1 and len({f.fragment_id for f in s.fragments}) == 3
    left, right, n = s.fragments
    assert left.paragraph_anchor == right.paragraph_anchor
    link = s.references[0]
    assert type(link) is api().NoteReference and link.kind == "footnote"
    assert (
        link.before_fragment_id == left.fragment_id and link.after_fragment_id == right.fragment_id
    )
    assert link.reference_anchor.path == (0, 0, 0, 1)
    assert link.paragraph_anchor == left.paragraph_anchor
    assert link.target_anchor == n.story_anchor and n.story_anchor.path == (0,)
    assert n.story_anchor.part_name == "custom/Foot.xml" and n.paragraph_anchor.path == (0, 0)
    assert n.flow_anchor == n.story_anchor and n.pieces[0].anchor.path == (0, 0, 0, 1)
    for f in s.fragments:
        root = ET.fromstring(
            xml if f.story_anchor.part_name == s.main_part else parts[f.story_anchor.part_name]
        )
        assert resolve(root, f.pieces[0].anchor).text == f.text
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and build(raw) == s
    assert {
        ("metadata", "note_reference"),
        ("metadata", "note_number_marker"),
        ("excluded", "unreferenced_note"),
    } <= codes(s)
    assert all(piece.kind in ("text", "tab", "break") for f in s.fragments for piece in f.pieces)
    assert "Foot 🧪" not in repr(s) + repr(link) and sha256(raw).hexdigest() == s.source_sha256
    with pytest.raises(FrozenInstanceError):
        link.kind = "endnote"


def test_first_use_order_same_id_different_kinds_and_repeated_reference_deduplication():
    body = p(ref("2", "endnote") + literal("Main") + ref() + ref())
    s = build(fixture(body)[0])
    assert s.complete and s.analysis_text == "Main\n\nEnd\n\nFoot 🧪"
    assert [r.kind for r in s.references] == ["endnote", "footnote", "footnote"]
    assert s.references[1].target_anchor == s.references[2].target_anchor
    assert s.references[0].target_anchor != s.references[1].target_anchor
    assert s.references[0].before_fragment_id is None
    assert s.references[0].after_fragment_id == s.fragments[0].fragment_id
    assert all(
        r.before_fragment_id == s.fragments[0].fragment_id and r.after_fragment_id is None
        for r in s.references[1:]
    )


def test_consecutive_markers_and_marker_only_paragraph_keep_links_without_fake_text():
    body = p(ref() + ref() + literal("A") + ref() + ref() + literal("B") + ref()) + p(ref())
    s = build(fixture(body)[0])
    assert s.complete and s.analysis_text == "A\n\nB\n\nFoot 🧪"
    a, b = s.fragments[:2]
    assert [(r.before_fragment_id, r.after_fragment_id) for r in s.references] == [
        (None, a.fragment_id),
        (None, a.fragment_id),
        (a.fragment_id, b.fragment_id),
        (a.fragment_id, b.fragment_id),
        (b.fragment_id, None),
        (None, None),
    ]
    assert len(s.paragraphs) == 3 and len(s.references) == 6


@pytest.mark.parametrize("identity", ["0", "-1", "-2147483648", "32767"])
def test_normal_note_ids_do_not_use_magic_separator_numbers(identity):
    s = build(fixture(p(ref(identity)), foot=note(identity, content=paragraph("Normal")))[0])
    assert s.complete and s.analysis_text == "Normal" and len(s.references) == 1


def test_section_stories_and_note_stories_keep_separate_original_owners():
    extras = {
        "custom/H.xml": story_xml(paragraph("Header")),
        "custom/F.xml": story_xml(paragraph("Footer"), "footer"),
    }
    links = [
        {"Id": "H", "Type": R + "header", "Target": "H.xml"},
        {"Id": "F", "Type": R + "footer", "Target": "F.xml"},
        {"Id": "N", "Type": R + "footnotes", "Target": "Foot.xml"},
    ]
    s = build(
        fixture(
            p(literal("Main") + ref()) + section(reference() + reference("F", "footer")),
            extras=extras,
            types={"custom/H.xml": BASE + "header+xml", "custom/F.xml": BASE + "footer+xml"},
            links=links,
        )[0]
    )
    assert s.complete and s.analysis_text == "Main\n\nFooter\n\nHeader\n\nFoot 🧪"
    assert [f.story_anchor.path for f in s.fragments] == [(0,), (), (), (0,)]
    assert s.references[0].target_anchor == s.fragments[-1].story_anchor


def test_hidden_deleted_and_historical_references_do_not_activate_missing_notes():
    body = "<w:p><w:r><w:t>A</w:t></w:r>"
    body += (
        '<w:r><w:rPr><w:rStyle w:val="Hide"/></w:rPr>'
        + ref("999", attrs=' w:customMarkFollows="true"')
        + "</w:r>"
    )
    body += '<w:del w:id="1"><w:r>' + ref("998") + "</w:r></w:del>"
    body += (
        '<w:r><w:rPr><w:rPrChange w:id="2"><w:rPr>'
        + ref("997")
        + "</w:rPr></w:rPrChange></w:rPr><w:t>B</w:t></w:r></w:p>"
    )
    styles = style("Hide", "<w:rPr><w:vanish/></w:rPr>", kind="character")
    s = build(fixture(body, styles=styles)[0])
    assert s.complete and s.analysis_text == "AB" and s.references == ()
    assert {
        ("excluded", "hidden_run"),
        ("excluded", "deleted_content"),
        ("excluded", "historical_properties"),
    } <= codes(s)


def test_inserted_and_moved_visible_references_activate_only_destination_notes():
    body = '<w:p><w:ins w:id="3"><w:r>' + ref() + "</w:r></w:ins>"
    body += group(content="<w:r>" + ref("999") + "</w:r>")
    body += group("To", content="<w:r>" + ref("2", "endnote") + "</w:r>") + "</w:p>"
    s = build(fixture(body)[0])
    assert s.complete and s.analysis_text == "Foot 🧪\n\nEnd"
    assert [r.kind for r in s.references] == ["footnote", "endnote"]


def test_note_tables_reuse_style_history_revisions_and_original_cell_offsets():
    removed = cell(paragraph("OLD"), marker("cellDel"))
    kept = cell(paragraph("Kept"), marker("cellIns") + history("cell"))
    content = table(row(removed + kept, marker("ins")), 0, '<w:tblStyle w:val="T"/>')
    raw, _, parts = fixture(p(ref()), foot=note(content=content), styles=table_style("T"))
    s = build(raw)
    assert s.complete and s.analysis_text == "Kept"
    f = s.fragments[0]
    assert f.story_anchor.path == (0,) and f.flow_anchor.path == (0, 0, 2, 2)
    assert resolve(ET.fromstring(parts["custom/Foot.xml"]), f.pieces[0].anchor).text == "Kept"
    assert {
        ("metadata", "derived_table_grid"),
        ("metadata", "table_style_proven"),
        ("excluded", "deleted_table_cell"),
        ("excluded", "historical_table_properties"),
    } <= codes(s)


def test_nested_note_table_and_main_cell_reference_keep_independent_flows():
    nested = gridless(row(cell(paragraph("Nested"))))
    content = gridless(row(cell(paragraph("Outer") + nested + paragraph("Tail"))))
    raw, _, _ = fixture(gridless(row(cell(p(ref())))), foot=note(content=content))
    s = build(raw)
    assert s.complete and s.analysis_text == "Outer\n\nNested\n\nTail"
    assert s.fragments[0].flow_anchor == s.fragments[2].flow_anchor
    assert s.fragments[0].flow_anchor != s.fragments[1].flow_anchor
    assert s.references[0].paragraph_anchor.part_name == s.main_part


def test_note_run_visibility_and_its_own_hyperlink_relationship_are_used():
    content = "<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>HIDDEN</w:t></w:r>"
    content += '<w:hyperlink r:id="Own">' + run("Linked") + "</w:hyperlink></w:p>"
    link = {
        "Id": "Own",
        "Type": R + "hyperlink",
        "Target": "https://invalid.example",
        "TargetMode": "External",
    }
    s = build(fixture(p(ref()), foot=note(content=content), foot_links=[link])[0])
    assert s.complete and s.analysis_text == "Linked"
    s = build(
        fixture(
            p(ref()),
            foot=note(content=content),
            links=[link, {"Id": "N", "Type": R + "footnotes", "Target": "Foot.xml"}],
        )[0]
    )
    assert not s.complete and s.fragments == s.references == () and s.analysis_text == ""


def test_orphan_and_special_payload_exclusion_requires_full_active_content_proof():
    foot = note("2", content=paragraph("Used")) + note(
        "7", content="<w:unknown>" + paragraph("UNUSED") + "</w:unknown>"
    )
    foot += note("0", "separator", content="<w:unknown>" + paragraph("SPECIAL") + "</w:unknown>")
    raw = fixture(p(ref()), foot=foot)[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Used"
    assert {("excluded", "unreferenced_note"), ("excluded", "special_note")} <= codes(s)
    raw = fixture(p(ref()) + "<w:unknown/>", foot=foot)[0]
    s = build(raw)
    assert not s.complete and s.fragments == s.references == s.paragraphs == s.runs == ()
    assert not ({("excluded", "unreferenced_note"), ("excluded", "special_note")} & codes(s))


@pytest.mark.parametrize(
    "body,foot,links,code",
    [
        (p(ref("99")), None, None, "unresolved_note_reference"),
        (p(ref()), None, [], "unresolved_note_reference"),
        (p(ref()), note("2", "separator"), None, "unresolved_note_reference"),
        (p(ref(attrs=' w:customMarkFollows="1"')), None, None, "unsupported_custom_note_mark"),
        (p(ref("32768")), note("32768"), None, "unsupported_note_identifier"),
        (p(ref("-2147483649")), note("-2147483649"), None, "unsupported_note_identifier"),
    ],
)
def test_unresolved_active_reference_never_publishes_a_valid_looking_prefix(
    body, foot, links, code
):
    s = build(fixture(paragraph("Good prefix") + body, foot=foot, links=links)[0])
    assert (
        not s.complete
        and s.analysis_text == ""
        and s.fragments == s.references == s.paragraphs == s.runs == ()
    )
    assert ("blocked", code) in codes(s)


@pytest.mark.parametrize(
    "attrs",
    [' w:customMarkFollows="0"', ' w:customMarkFollows="false"', ' w:customMarkFollows="off"'],
)
def test_explicit_false_custom_marker_keeps_ordinary_generated_boundary(attrs):
    s = build(fixture(p(literal("A") + ref(attrs=attrs) + literal("B")))[0])
    assert s.complete and s.analysis_text == "A\n\nB\n\nFoot 🧪"


@pytest.mark.parametrize(
    "content", [p(ref()), p("<w:endnoteRef/>"), p('<w:footnoteRef w:id="2"/>'), "<w:unknown/>"]
)
def test_invalid_or_unsupported_active_note_content_blocks_whole_snapshot(content):
    s = build(fixture(foot=note(content=content))[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.references == ()


def test_header_note_reference_stays_explicit_context_gate():
    links = [
        {"Id": "H", "Type": R + "header", "Target": "H.xml"},
        {"Id": "N", "Type": R + "footnotes", "Target": "Foot.xml"},
    ]
    s = build(
        fixture(
            paragraph("Body") + section(reference()),
            extras={"custom/H.xml": story_xml(p(ref()))},
            types={"custom/H.xml": BASE + "header+xml"},
            links=links,
        )[0]
    )
    assert not s.complete and s.fragments == s.references == ()
    assert ("blocked", "unsupported_note_reference_context") in codes(s)


def test_per_note_inline_move_pairs_never_pair_across_distinct_definitions():
    moved = "<w:p>" + group(content=run("Old")) + group("To", content=run("Kept")) + "</w:p>"
    second = (
        "<w:p>"
        + group(identity="8", name="second", content=run("Old"))
        + group("To", identity="9", name="second", content=run("Kept"))
        + "</w:p>"
    )
    raw = fixture(p(ref() + ref("3")), foot=note("2", content=moved) + note("3", content=second))[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Kept\n\nKept"
    assert [f.story_anchor.path for f in s.fragments] == [(0,), (1,)]
    cross = note("2", content="<w:p>" + group() + "</w:p>") + note(
        "3", content="<w:p>" + group("To") + "</w:p>"
    )
    s = build(fixture(p(ref() + ref("3")), foot=cross)[0])
    assert (
        not s.complete
        and s.fragments == s.references == ()
        and ("blocked", "move_catalog_blocked") in codes(s)
    )


def test_no_notes_uses_new_profile_without_changing_previous_story_reader():
    raw = source(paragraph("Body"))[0]
    s = build(raw)
    old = import_module("ara.docx_analysis.visible_stories").build_story_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert s.complete and s.analysis_text == old.analysis_text == "Body" and s.references == ()
    assert s.profile != old.profile and s.fragments[0].fragment_id != old.fragments[0].fragment_id
    note_raw = fixture()[0]
    unsupported = import_module("ara.docx_analysis.visible_stories").build_story_snapshot(
        note_raw,
        document_id=DOC,
        storage_revision=7,
        source_sha256=sha256(note_raw).hexdigest(),
    )
    assert not unsupported.complete and unsupported.fragments == ()


@pytest.mark.parametrize("active", [False, True])
def test_duplicate_move_starts_across_same_part_notes_remain_ambiguous(active):
    moved = "<w:p>" + group(content=run("Old")) + group("To", content=run("Kept")) + "</w:p>"
    body = p(ref() + (ref("3") if active else ""))
    raw = fixture(body, foot=note("2", content=moved) + note("3", content=moved))[0]
    s = build(raw)
    assert not s.complete and s.fragments == s.references == ()
    assert ("blocked", "move_catalog_blocked") in codes(s)
