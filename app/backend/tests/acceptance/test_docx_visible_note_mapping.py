"""Exact source slices and whole-original verification include note-reference context."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_note_catalog import note
from test_docx_table_catalog import paragraph
from test_docx_visible_main import DOC, rehash
from test_docx_visible_notes import api, build, error, fixture, literal, p, ref, request


def test_identical_words_separated_by_reference_and_inside_note_keep_three_source_slices():
    raw, xml, parts = fixture(
        p(literal("Same") + ref() + literal("Same")), foot=note(content=paragraph("Same"))
    )
    s = build(raw)
    assert s.complete and len({f.fragment_id for f in s.fragments}) == 3
    mapped = api().map_note_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    anchors = []
    for m in mapped:
        assert len(m.slices) == 1
        a = m.slices[0].anchor
        anchors.append(a)
        root = ET.fromstring(xml if a.part_name == s.main_part else parts[a.part_name])
        assert resolve(root, a).text[m.slices[0].start : m.slices[0].end] == "Same"
    assert (
        len(set(anchors)) == 3
        and anchors[0].part_name == anchors[1].part_name != anchors[2].part_name
    )
    error(
        "invalid_span",
        lambda: api().map_note_span(
            raw, s, fragment_id=s.fragments[0].fragment_id, start=0, end=8, quote="SameSame"
        ),
    )


def test_nonbmp_tabs_breaks_hidden_gaps_preserve_original_note_codepoint_offsets():
    content = "<w:p><w:r><w:footnoteRef/><w:t>Я😀</w:t><w:tab/></w:r>"
    content += "<w:r><w:rPr><w:vanish/></w:rPr><w:t>OLD</w:t></w:r>"
    content += "<w:r><w:t>é</w:t><w:br/><w:t>Z</w:t></w:r></w:p>"
    raw, _, parts = fixture(p(ref()), foot=note(content=content))
    s = build(raw)
    f = s.fragments[0]
    assert f.text == "Я😀\té\nZ"
    m = api().map_note_span(raw, s, fragment_id=f.fragment_id, start=1, end=6, quote="😀\té\n")
    assert [x.kind for x in m.slices] == ["text", "tab", "text", "break"]
    assert [(x.start, x.end) for x in m.slices] == [(1, 2), (0, 1), (0, 2), (0, 1)]
    assert [x.anchor.path for x in m.slices] == [
        (0, 0, 0, 1),
        (0, 0, 0, 2),
        (0, 0, 2, 0),
        (0, 0, 2, 1),
    ]
    assert all(x.anchor.part_name == "custom/Foot.xml" for x in m.slices)
    assert resolve(ET.fromstring(parts["custom/Foot.xml"]), m.slices[0].anchor).text == "Я😀"


@pytest.mark.parametrize("empty", [False, True])
def test_batch_rebuilds_all_source_proofs_once_and_parses_each_used_note_part_once(
    monkeypatch, empty
):
    raw = fixture(p(ref() + ref("3") + ref("4")), foot=note("2") + note("3") + note("4"))[0]
    s = build(raw)
    am = import_module("ara.docx_analysis.visible_notes._api")
    bm = import_module("ara.docx_analysis.visible_notes._build")
    pm = import_module("ara.docx_analysis.visible_notes._parse")
    sections = import_module("ara.docx_analysis.sections")
    notes = import_module("ara.docx_analysis.notes")
    counts = {"build": 0, "section": 0, "note": 0, "style": 0}

    def wrap(owner, name, key):
        original = getattr(owner, name)

        def counted(*a, **kw):
            counts[key] += 1
            return original(*a, **kw)

        monkeypatch.setattr(owner, name, counted)

    wrap(am, "build_note_snapshot", "build")
    wrap(sections, "read_section_catalog", "section")
    wrap(notes, "read_note_catalog", "note")
    wrap(bm, "read_style_context", "style")
    parsed = []
    original = pm.build_tree

    def parse(*a, **kw):
        parsed.append(a[1])
        return original(*a, **kw)

    monkeypatch.setattr(pm, "build_tree", parse)
    queries = () if empty else tuple(request(f) for f in s.fragments) * 4
    assert len(api().map_note_spans(raw, s, requests=queries)) == len(queries)
    assert counts == {"build": 1, "section": 1, "note": 1, "style": 1}
    assert parsed.count("custom/Foot.xml") == 1
    assert "custom/End.xml" not in parsed


@pytest.mark.parametrize(
    "change", ["target", "reference", "before", "kind", "remove", "profile", "text"]
)
def test_rehashed_forged_reference_context_or_text_never_becomes_a_valid_snapshot(change):
    raw = fixture()[0]
    s = build(raw)
    r = s.references[0]
    if change == "target":
        r = replace(r, target_anchor=replace(r.target_anchor, path=(99,)))
    elif change == "reference":
        r = replace(r, reference_anchor=replace(r.reference_anchor, path=(0, 0, 0, 0)))
    elif change == "before":
        r = replace(r, before_fragment_id=s.fragments[-1].fragment_id)
    elif change == "kind":
        r = replace(r, kind="endnote")
    s = replace(s, references=(r,))
    if change == "remove":
        s = replace(s, references=())
    elif change == "profile":
        s = replace(s, profile="docx-analysis/final-visible-section-stories-v1")
    elif change == "text":
        s = replace(s, analysis_text="Forged")
    s = rehash(s)
    error("invalid_snapshot", lambda: api().map_note_spans(raw, s, requests=()))


def test_old_profile_foreign_dto_missing_fields_and_changed_source_are_rejected():
    raw = fixture()[0]
    s = build(raw)
    previous = import_module("ara.docx_analysis.visible_stories")
    error("invalid_snapshot", lambda: previous.map_story_spans(raw, s, requests=()))
    from test_docx_visible_main import source

    old_raw = source(paragraph("Old"))[0]
    old = previous.build_story_snapshot(
        old_raw, document_id=DOC, storage_revision=7, source_sha256=sha256(old_raw).hexdigest()
    )
    error("invalid_snapshot", lambda: api().map_note_spans(old_raw, old, requests=()))
    error(
        "source_mismatch",
        lambda: api().map_note_spans(fixture(p(literal("Changed") + ref()))[0], s, requests=()),
    )
    bad = replace(s, references=[s.references[0]])
    error("invalid_snapshot", lambda: api().map_note_spans(raw, bad, requests=()))
    bad = replace(s)
    object.__delattr__(bad, "references")
    error("invalid_snapshot", lambda: api().map_note_spans(raw, bad, requests=()))
