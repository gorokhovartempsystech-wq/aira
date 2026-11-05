"""Source-derived neutral table styles, logical flows and exact original slices."""

from dataclasses import asdict, replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_visible_main import DOC, canonical, codes, payload, rehash, source, style

PROFILE = "docx-analysis/final-visible-neutral-tables-v1"
CNF = '<w:cnfStyle w:val="100000000000" w:firstRow="true"/>'


def api():
    return import_module("ara.docx_analysis.visible_styled_tables")


def build(raw, **kwargs):
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    return api().build_styled_table_snapshot(raw, **(identity | kwargs))


def request(f, start=0, end=None):
    end = len(f.text) if end is None else end
    return api().VisibleSpanRequest(f.fragment_id, start, end, f.text[start:end])


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


def table_style(key="T", content="", default=False):
    return style(key, content, kind="table", attrs='w:default="1"' if default else "")


def styled_table(text="Cell", key="T"):
    return table(
        row(cell(paragraph(text))),
        1,
        properties=f'<w:tblStyle w:val="{key}"/>' if key is not None else "",
    )


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_explicit_neutral_ancestry_original_cell_paths_and_profile(strict, encoding):
    body = paragraph("Before") + styled_table("Я😀é") + paragraph("After")
    styles = table_style(
        "Base", '<w:tblPr><w:tblBorders><w:top w:val="single"/></w:tblBorders></w:tblPr>'
    )
    styles += table_style(
        "T",
        '<w:basedOn w:val="Base"/><w:tblStylePr w:type="firstRow">'
        "<w:rPr><w:b/></w:rPr></w:tblStylePr>",
    )
    raw, xml = source(body, styles, strict=strict, encoding=encoding)
    s = build(raw)
    assert s.complete and s.profile == PROFILE and s.analysis_text == "Before\n\nЯ😀é\n\nAfter"
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    assert [f.flow_anchor.path for f in s.fragments] == [(0,), (0, 1, 2, 0), (0,)]
    assert ("metadata", "table_style_proven") in codes(s)
    f = s.fragments[1]
    expected = dict(
        domain="docx-visible-fragment/1",
        profile=PROFILE,
        policy_version=s.policy_version,
        source_sha256=s.source_sha256,
        story_anchor=asdict(f.story_anchor),
        flow_anchor=asdict(f.flow_anchor),
        paragraph_anchor=asdict(f.paragraph_anchor),
    )
    assert f.fragment_id == "vf-" + sha256(canonical(expected)).hexdigest()
    mapped = api().map_styled_table_spans(raw, s, requests=tuple(request(f) for f in s.fragments))
    assert [m.slices[0].anchor.path for m in mapped] == [
        (0, 0, 0, 0),
        (0, 1, 2, 0, 0, 0, 0),
        (0, 2, 0, 0),
    ]
    root = ET.fromstring(xml)
    assert [resolve(root, m.slices[0].anchor).text for m in mapped] == ["Before", "Я😀é", "After"]
    assert build(raw) == s and sha256(raw).hexdigest() == s.source_sha256


def test_default_explicit_override_and_unrelated_bad_style():
    definitions = table_style("Default", "<w:rPr><w:i/></w:rPr>", True)
    definitions += table_style("T") + table_style("Unused", "<w:rPr><w:vanish/></w:rPr>")
    raw = source(
        styled_table("Implicit", None) + paragraph("Gap") + styled_table("Explicit"), definitions
    )[0]
    s = build(raw)
    assert s.complete and s.analysis_text == "Implicit\n\nGap\n\nExplicit"
    bad_default = definitions.replace("<w:rPr><w:i/></w:rPr>", "<w:rPr><w:vanish/></w:rPr>")
    assert build(source(styled_table(), bad_default)[0]).complete
    s = build(source(styled_table(key=None), bad_default)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()
    assert ("blocked", "unresolved_table_style") in codes(s)


def test_nested_table_uses_own_default_not_outer_selector_and_keeps_flows():
    nested = styled_table("Inner", None)
    outer = table(
        row(cell(paragraph("Outer") + nested + paragraph("Tail"))),
        1,
        properties='<w:tblStyle w:val="T"/>',
    )
    definitions = table_style("T") + table_style("Default", default=True)
    s = build(source(outer, definitions)[0])
    assert s.complete and s.analysis_text == "Outer\n\nInner\n\nTail"
    assert [f.flow_anchor.path for f in s.fragments] == [
        (0, 0, 2, 0),
        (0, 0, 2, 0, 1, 1, 0),
        (0, 0, 2, 0),
    ]
    bad = table_style("T") + table_style("Default", "<w:rPr><w:vanish/></w:rPr>", True)
    s = build(source(outer, bad)[0])
    assert not s.complete and ("blocked", "unresolved_table_style") in codes(s)


@pytest.mark.parametrize(
    "selector,definitions,code",
    [
        ("Missing", table_style(), "missing_table_style"),
        ("P", style("P"), "table_style_type_mismatch"),
        (
            "T",
            table_style(content='<w:rPr><w:vanish w:val="false"/></w:rPr>'),
            "unresolved_table_style",
        ),
        ("T", table_style(content='<w:basedOn w:val="Missing"/>'), "unresolved_table_style"),
        (
            "T",
            table_style(
                content='<w:tblStylePr w:type="lastRow"><w:rPr><w:vanish/></w:rPr></w:tblStylePr>'
            ),
            "unresolved_table_style",
        ),
        (
            "T",
            table_style(content="<w:pPr><w:rPr><w:specVanish/></w:rPr></w:pPr>"),
            "unresolved_table_style",
        ),
    ],
)
def test_used_unresolved_styles_cannot_be_bypassed_by_direct_visible_runs(
    selector, definitions, code
):
    body = styled_table(key=selector).replace(
        "<w:r>", '<w:r><w:rPr><w:vanish w:val="false"/></w:rPr>'
    )
    s = build(source(paragraph("Prefix") + body, definitions)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == s.runs == s.paragraphs == ()
    assert ("blocked", code) in codes(s)


@pytest.mark.parametrize(
    "selector",
    [
        "<w:tblStyle/>",
        '<w:tblStyle w:val=""/>',
        '<w:tblStyle w:val="T" w:extra="x"/>',
        '<w:tblStyle w:val="T"><w:unknown/></w:tblStyle>',
        '<w:tblStyle w:val="T"/><w:tblStyle w:val="T"/>',
    ],
)
def test_malformed_selectors_are_not_absent(selector):
    s = build(source(table(properties=selector), table_style())[0])
    assert not s.complete and s.fragments == ()
    assert ("blocked", "unsupported_table_properties") in codes(s)


def test_conditional_markers_only_metadata_and_hidden_gap_mapping_is_preserved():
    p = "<w:p><w:pPr>" + CNF + "</w:pPr><w:r><w:t>ab</w:t></w:r>"
    p += '<w:r><w:rPr><w:rStyle w:val="Hidden"/></w:rPr><w:t>SECRET</w:t></w:r>'
    p += "<w:r><w:t>cd</w:t></w:r></w:p>"
    body = table(
        row(cell(p, CNF), properties=CNF),
        1,
        properties='<w:tblStyle w:val="T"/><w:tblStyleRowBandSize w:val="2"/>'
        '<w:tblStyleColBandSize w:val="1"/>',
    )
    definitions = table_style(
        content='<w:tblStylePr w:type="firstRow"><w:rPr><w:b/></w:rPr></w:tblStylePr>'
    )
    definitions += style("Hidden", "<w:rPr><w:vanish/></w:rPr>", kind="character")
    raw, xml = source(body, definitions)
    s = build(raw)
    assert s.complete and s.analysis_text == "abcd"
    assert sum(c.code == "conditional_table_format" for c in s.coverage) == 3
    f = s.fragments[0]
    result = api().map_styled_table_span(
        raw, s, fragment_id=f.fragment_id, start=1, end=3, quote="bc"
    )
    assert [resolve(ET.fromstring(xml), x.anchor).text[x.start : x.end] for x in result.slices] == [
        "b",
        "c",
    ]
    assert ("excluded", "hidden_run") in codes(s)
    assert "SECRET" not in repr(s)


def test_cnf_in_ordinary_body_paragraph_is_known_inactive_metadata():
    body = "<w:p><w:pPr>" + CNF + "</w:pPr><w:r><w:t>Body</w:t></w:r></w:p>"
    s = build(source(body)[0])
    assert s.complete and s.analysis_text == "Body"
    assert ("metadata", "conditional_table_format") in codes(s)


@pytest.mark.parametrize(
    "content",
    [
        '<w:cnfStyle w:val="100"/>',
        '<w:cnfStyle w:val="10000000000X"/>',
        '<w:cnfStyle w:firstRow="TRUE"/>',
        '<w:cnfStyle w:unknown="1"/>',
        "<w:cnfStyle><w:r/></w:cnfStyle>",
        "<w:cnfStyle>PAYLOAD</w:cnfStyle>",
        "<w:cnfStyle/><w:cnfStyle/>",
    ],
)
def test_invalid_conditional_metadata_is_not_ignored(content):
    raw = source(table(row(cell(properties=content)), 1), table_style(default=True))[0]
    s = build(raw)
    assert not s.complete and s.fragments == ()
    assert ("blocked", "unsupported_table_properties") in codes(s)


@pytest.mark.parametrize("location", ["rPr", "mark"])
def test_conditional_metadata_does_not_extend_run_or_mark_grammar(location):
    if location == "rPr":
        p = "<w:p><w:r><w:rPr>" + CNF + "</w:rPr><w:t>Text</w:t></w:r></w:p>"
    else:
        p = "<w:p><w:pPr><w:rPr>" + CNF + "</w:rPr></w:pPr><w:r><w:t>Text</w:t></w:r></w:p>"
    s = build(source(table(row(cell(p)), 1), table_style(default=True))[0])
    assert not s.complete and s.fragments == ()


def test_boundary_and_other_part_guards_remain_despite_neutral_table_style():
    defaults = (
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>"
    )
    s = build(source(styled_table(), defaults + table_style())[0])
    assert not s.complete and s.fragments == ()
    assert ("blocked", "unresolved_paragraph_boundary") in codes(s)
    raw = source(
        styled_table(),
        table_style(),
        extra_parts={"custom/settings.xml": b"<settings/>"},
        extra_types={
            "custom/settings.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
            )
        },
    )[0]
    s = build(raw)
    assert not s.complete and ("blocked", "unread_part") in codes(s)


def test_old_table_profile_guards_and_mutual_profile_rejection():
    old = import_module("ara.docx_analysis.visible_tables")
    raw = source(styled_table(), table_style())[0]
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    previous = old.build_table_snapshot(raw, **identity)
    assert not previous.complete and ("blocked", "unresolved_table_style") in codes(previous)
    s = build(raw)
    assert s.complete
    error("invalid_snapshot", lambda: old.map_table_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_styled_table_spans(raw, previous, requests=()))
    forged = rehash(replace(s, profile=previous.profile))
    error("invalid_snapshot", lambda: old.map_table_spans(raw, forged, requests=()))


def test_changed_styles_or_rehashed_caller_context_cannot_supply_proof():
    raw = source(styled_table(), table_style())[0]
    s = build(raw)
    changed = source(styled_table(), table_style(content="<w:rPr><w:vanish/></w:rPr>"))[0]
    error("source_mismatch", lambda: api().map_styled_table_spans(changed, s, requests=()))
    forged = rehash(replace(s, style_context=replace(s.style_context, styles=())))
    error("invalid_snapshot", lambda: api().map_styled_table_spans(raw, forged, requests=()))
    f = s.fragments[0]
    forged = rehash(replace(s, fragments=(replace(f, flow_anchor=f.story_anchor),)))
    error("invalid_snapshot", lambda: api().map_styled_table_spans(raw, forged, requests=()))
