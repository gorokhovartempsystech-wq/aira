"""Whole-original batch verification maps quotes into their own story parts."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_visible_main import DOC, rehash
from test_docx_visible_stories import api, build, error, fixture, paragraph, request


def test_equal_quotes_across_three_parts_have_distinct_fragment_and_source_addresses():
    from test_docx_section_catalog import reference, section

    raw, xml, parts = fixture(
        paragraph("Same") + section(reference() + reference("F", "footer")),
        header=paragraph("Same"),
        footer=paragraph("Same"),
    )
    s = build(raw)
    assert s.complete and len({f.fragment_id for f in s.fragments}) == 3
    mapped = api().map_story_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    assert [m.slices[0].anchor.part_name for m in mapped] == [
        "custom/Main.xml",
        "custom/F.xml",
        "custom/H.xml",
    ]
    for m in mapped:
        a = m.slices[0].anchor
        root = ET.fromstring(xml if a.part_name == s.main_part else parts[a.part_name])
        assert resolve(root, a).text[m.slices[0].start : m.slices[0].end] == "Same"


def test_unicode_tabs_breaks_hidden_gap_and_exact_source_slices_in_header():
    header = (
        "<w:p><w:r><w:t>Я😀</w:t><w:tab/></w:r>"
        "<w:r><w:rPr><w:vanish/></w:rPr><w:t>OLD</w:t></w:r>"
        "<w:r><w:t>é</w:t><w:br/><w:t>Z</w:t></w:r></w:p>"
    )
    raw, _, parts = fixture(header=header)
    s = build(raw)
    f = s.fragments[-1]
    assert f.text == "Я😀\té\nZ"
    m = api().map_story_span(raw, s, fragment_id=f.fragment_id, start=1, end=6, quote="😀\té\n")
    assert [x.kind for x in m.slices] == ["text", "tab", "text", "break"]
    assert [(x.start, x.end) for x in m.slices] == [(1, 2), (0, 1), (0, 2), (0, 1)]
    assert [x.anchor.path for x in m.slices] == [(0, 0, 0), (0, 0, 1), (0, 2, 0), (0, 2, 1)]
    assert all(x.anchor.part_name == "custom/H.xml" for x in m.slices)
    assert resolve(ET.fromstring(parts["custom/H.xml"]), m.slices[0].anchor).text == "Я😀"
    error(
        "invalid_span",
        lambda: api().map_story_span(raw, s, fragment_id=f.fragment_id, start=0, end=1, quote="😀"),
    )


@pytest.mark.parametrize("empty", [False, True])
def test_one_fresh_section_style_and_snapshot_build_per_batch_including_empty(monkeypatch, empty):
    raw = fixture()[0]
    s = build(raw)
    public = api()
    builder = import_module("ara.docx_analysis.visible_stories._api")
    build_module = import_module("ara.docx_analysis.visible_stories._build")
    sections = import_module("ara.docx_analysis.sections")
    counts = {"build": 0, "section": 0, "style": 0}

    def count(owner, name, key):
        original = getattr(owner, name)

        def wrapped(*a, **kw):
            counts[key] += 1
            return original(*a, **kw)

        monkeypatch.setattr(owner, name, wrapped)

    count(builder, "build_story_snapshot", "build")
    count(sections, "read_section_catalog", "section")
    count(build_module, "read_style_context", "style")
    queries = () if empty else tuple(request(f) for f in s.fragments) * 4
    mapped = public.map_story_spans(raw, s, requests=queries)
    assert len(mapped) == len(queries) and counts == {"build": 1, "section": 1, "style": 1}


@pytest.mark.parametrize("change", ["quote", "story_part", "coverage", "profile", "style"])
def test_rehashed_foreign_snapshot_cannot_authorize_mapping(change):
    raw = fixture()[0]
    s = build(raw)
    f = s.fragments[-1]
    if change == "quote":
        changed = replace(s, fragments=(*s.fragments[:-1], replace(f, text="FORGED")))
    elif change == "story_part":
        a = replace(f.story_anchor, part_name="custom/F.xml")
        changed = replace(s, fragments=(*s.fragments[:-1], replace(f, story_anchor=a)))
    elif change == "coverage":
        changed = replace(
            s, coverage=tuple(e for e in s.coverage if e.code != "header_footer_reference")
        )
        assert changed != s
    elif change == "profile":
        changed = replace(s, profile="docx-analysis/final-visible-grid-tables-v1")
    else:
        changed = replace(s, style_context=replace(s.style_context, source_sha256="0" * 64))
    changed = rehash(changed)
    error("invalid_snapshot", lambda: api().map_story_spans(raw, changed, requests=()))


def test_old_profile_and_changed_package_fail_without_quote_search():
    raw = fixture()[0]
    s = build(raw)
    changed = fixture(header=paragraph("Different"))[0]
    error("source_mismatch", lambda: api().map_story_spans(changed, s, requests=()))
    error(
        "unknown_fragment",
        lambda: api().map_story_spans(
            raw, s, requests=(api().VisibleSpanRequest("vf-" + "0" * 64, 0, 4, "Body"),)
        ),
    )
    old = import_module("ara.docx_analysis.visible_grid_tables")
    prior = old.build_grid_table_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    error("invalid_snapshot", lambda: api().map_story_spans(raw, prior, requests=()))


def test_batch_limits_are_aggregate_across_stories():
    raw = fixture()[0]
    s = build(raw)
    queries = tuple(request(f) for f in s.fragments)
    for kw in (
        dict(max_span_requests=2),
        dict(max_requested_characters=15),
        dict(max_mapped_slices=2),
    ):
        error(
            "view_limit_exceeded",
            lambda kw=kw: api().map_story_spans(
                raw, s, requests=queries, limits=api().VisibleLimits(**kw)
            ),
        )
    assert (
        len(
            api().map_story_spans(
                raw,
                s,
                requests=queries,
                limits=api().VisibleLimits(
                    max_span_requests=3, max_requested_characters=16, max_mapped_slices=3
                ),
            )
        )
        == 3
    )
