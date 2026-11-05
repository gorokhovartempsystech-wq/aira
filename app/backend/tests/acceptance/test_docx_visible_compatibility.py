"""Selected visible stories retain exact addresses in the unchanged source package."""

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_compatibility_catalog import MAIN, alternate, choice
from test_docx_compatibility_contexts import fixture
from test_docx_move_catalog import group, resolve, run
from test_docx_note_catalog import note
from test_docx_retained_tables import marker
from test_docx_section_catalog import reference, section
from test_docx_table_catalog import cell, paragraph, row, table
from test_docx_table_styles import table_style
from test_docx_visibility_styles import style
from test_docx_visible_controls import control
from test_docx_visible_fields import char, instr, simple
from test_docx_visible_main import DOC, canonical, codes, payload, rehash
from test_docx_visible_notes import literal, p, ref

PROFILE = "docx-analysis/final-visible-compatibility-v1"


def api():
    return import_module("ara.docx_analysis.visible_compatibility")


def build(raw, **kw):
    identity = dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest())
    return api().build_compatibility_snapshot(raw, **(identity | kw))


def selected(content):
    return alternate(choice("x", "<w:unsupported/>") + choice("w", content))


def request(f):
    return api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text)


def error(code, call):
    with pytest.raises(api().VisibleViewError) as caught:
        call()
    assert caught.value.code == code


def assert_original(raw, parts, snapshot):
    roots = {part: ET.fromstring(xml) for part, xml in parts.items()}
    mapped = api().map_compatibility_spans(
        raw, snapshot, requests=tuple(request(f) for f in snapshot.fragments)
    )
    for fragment, result in zip(snapshot.fragments, mapped, strict=True):
        assert resolve(
            roots[fragment.paragraph_anchor.part_name], fragment.paragraph_anchor
        ).tag.endswith("}p")
        texts = []
        for item in result.slices:
            assert item.anchor.source_sha256 == sha256(raw).hexdigest()
            node = resolve(roots[item.anchor.part_name], item.anchor)
            value = node.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            texts.append(value[item.start : item.end])
            assert resolve(roots[item.run_anchor.part_name], item.run_anchor).tag.endswith("}r")
        assert "".join(texts) == fragment.text


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_main_selection_and_mapping_keep_original_unicode_paths(strict, encoding):
    body = selected("<w:p>" + run("A") + selected(run("Я😀é")) + run("Z") + "</w:p>")
    raw, parts = fixture(body, strict=strict, encoding=encoding)
    before = raw
    s = build(raw)
    assert s.complete and s.analysis_text == "AЯ😀éZ" and s.profile == PROFILE
    assert s.style_context.profile == "docx-visibility/mc-styles-context-v1"
    assert s == build(raw) and s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest()
    f = s.fragments[0]
    assert f.paragraph_anchor.path == (0, 0, 1, 0)
    assert f.pieces[1].anchor.path == (0, 0, 1, 0, 1, 1, 0, 0)
    m = api().map_compatibility_span(raw, s, fragment_id=f.fragment_id, start=2, end=3, quote="😀")
    assert (m.slices[0].start, m.slices[0].end) == (1, 2)
    assert m.slices[0].anchor == f.pieces[1].anchor and raw == before
    assert_original(raw, parts, s)


@pytest.mark.parametrize(
    "kind,expected", [("fallback", "Fallback"), ("none", ""), ("first", "First")]
)
def test_choice_fallback_and_empty_selection_do_not_read_discarded_content(kind, expected):
    branches = choice("x", "<w:unsupported/>")
    if kind == "fallback":
        branches += "<mc:Fallback>" + paragraph("Fallback") + "</mc:Fallback>"
    elif kind == "first":
        branches += choice("w", paragraph("First")) + choice("w", "<w:unsupported/>")
    raw, parts = fixture(alternate(branches))
    s = build(raw)
    assert s.complete and s.analysis_text == expected
    assert ("metadata", "compatibility_alternate_selection") in codes(s)
    assert_original(raw, parts, s)


def test_process_content_ignored_subtree_and_attributes_preserve_literal_node_text():
    raw, parts = fixture(
        '<x:drop><w:unsupported/></x:drop><x:unwrap><w:p x:unused="PRIVATE_ATTR">'
        '<w:r><w:t xml:space="preserve"> A 😀 </w:t></w:r></w:p></x:unwrap>',
        attrs='mc:Ignorable="x" mc:ProcessContent="x:unwrap"',
    )
    s = build(raw)
    assert s.complete and s.analysis_text == " A 😀 "
    assert {
        ("excluded", "compatibility_ignored_element"),
        ("metadata", "compatibility_unwrapped_element"),
        ("metadata", "compatibility_attributes"),
    } <= codes(s)
    assert "PRIVATE_ATTR" not in repr(s) and " A 😀 " not in repr(s)
    assert_original(raw, parts, s)


def test_selected_styles_apply_to_selected_runs_with_original_property_provenance():
    styles = selected(style("Hidden", "<w:rPr><w:vanish/></w:rPr>", kind="character"))
    hidden = (
        "<w:r><w:rPr>" + selected('<w:rStyle w:val="Hidden"/>') + "</w:rPr><w:t>SECRET</w:t></w:r>"
    )
    raw, parts = fixture("<w:p>" + run("A") + selected(hidden) + run("B") + "</w:p>", styles=styles)
    s = build(raw)
    assert s.complete and s.analysis_text == "AB" and len(s.runs) == 3
    assert s.runs[1].visibility.hidden and ("excluded", "hidden_run") in codes(s)
    anchor = s.style_context.styles[0].properties.vanish.anchor
    assert resolve(ET.fromstring(parts[anchor.part_name]), anchor).tag.endswith("}vanish")
    assert_original(raw, parts, s)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_sections_headers_and_nested_note_definitions_share_selected_contexts(strict, encoding):
    body = selected(p(literal("Before") + selected(ref()) + literal("After")))
    body += selected(section(reference("H")))
    foot = selected(note("2", content=selected(p("<w:footnoteRef/>" + literal("Note 🧪")))))
    raw, parts = fixture(
        body,
        foot=foot,
        header=selected(paragraph("Header")),
        settings=selected("<w:evenAndOddHeaders/>"),
        strict=strict,
        encoding=encoding,
    )
    s = build(raw)
    assert s.complete and [f.text for f in s.fragments] == ["Before", "After", "Header", "Note 🧪"]
    assert len(s.references) == 1 and s.references[0].target_anchor.path == (0, 1, 0)
    target = s.references[0].target_anchor
    assert resolve(ET.fromstring(parts[target.part_name]), target).tag.endswith("}footnote")
    assert s.fragments[-1].story_anchor == target
    assert_original(raw, parts, s)


@pytest.mark.parametrize("level", ["table", "row", "cell", "all"])
def test_selected_table_control_hierarchy_retains_actual_cell_flow(level):
    content = control(selected(paragraph("Cell😀")))
    c = cell(content)
    if level in ("cell", "all"):
        c = selected(control(c))
    r = row(c)
    if level in ("row", "all"):
        r = control(selected(r))
    body = table(r, 1, selected('<w:tblStyle w:val="T"/>'))
    if level in ("table", "all"):
        body = selected(control(body))
    raw, parts = fixture(body, styles=selected(table_style("T", "<w:rPr><w:b/></w:rPr>")))
    s = build(raw)
    assert s.complete and s.analysis_text == "Cell😀"
    assert resolve(ET.fromstring(parts[MAIN]), s.fragments[0].flow_anchor).tag.endswith("}tc")
    assert ("metadata", "table_style_proven") in codes(s)
    assert_original(raw, parts, s)


def test_selected_deleted_cell_marker_and_property_history_keep_original_addresses(monkeypatch):
    geometry = import_module("ara.docx_analysis.visible_control_tables._reader").ControlGeometry
    original, facts = geometry.__init__, []

    def capture(self, context, limits):
        facts.extend(context.histories)
        facts.extend(context.revisions)
        original(self, context, limits)

    monkeypatch.setattr(geometry, "__init__", capture)
    hist = '<w:tcPrChange w:id="4">' + selected("<w:tcPr><w:unknown/></w:tcPr>") + "</w:tcPrChange>"
    deleted = cell(paragraph("DELETED"), selected(marker("cellDel")))
    kept = cell(paragraph("Kept"), selected(marker("cellIns")) + selected(hist))
    raw, parts = fixture(table(row(selected(deleted) + selected(kept)), 1))
    s = build(raw)
    assert s.complete and s.analysis_text == "Kept" and facts
    root = ET.fromstring(parts[MAIN])
    for fact in facts:
        if hasattr(fact, "previous_anchor"):
            assert resolve(root, fact.previous_anchor).tag.endswith("}tcPr")
        else:
            assert resolve(root, fact.anchor).tag.endswith(
                "}cellDel" if fact.kind == "deleted_cell" else "}cellIns"
            )
            assert resolve(root, fact.owner_anchor).tag.endswith("}tcPr")
            assert resolve(root, fact.subject_anchor).tag.endswith("}tc")
    assert_original(raw, parts, s)


def test_move_ranges_use_the_actual_logical_paragraph_anchor():
    body = selected(
        "<w:p>"
        + selected(group(content=run("OLD")))
        + run("A")
        + selected(group("To", content=run("New")))
        + "</w:p>"
    )
    raw, parts = fixture(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "ANew"
    assert ("excluded", "moved_source") in codes(s)
    assert_original(raw, parts, s)


def test_compatibility_wrappers_are_transparent_to_fields_but_control_boundaries_are_not():
    field = (
        char("begin")
        + instr("AUTHOR")
        + selected(char("separate") + literal("Result"))
        + char("end")
    )
    raw, parts = fixture(p(field))
    s = build(raw)
    assert s.complete and s.analysis_text == "Result"
    assert_original(raw, parts, s)
    bad = "<w:p>" + run("")  # runs containing field tokens, not literal text
    bad += "<w:r>" + char("begin") + instr() + "</w:r>" + selected(control(""))
    bad += "<w:r>" + char("separate") + literal("No") + char("end") + "</w:r></w:p>"
    s = build(fixture(bad)[0])
    assert not s.complete and s.analysis_text == "" and s.fragments == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(body=selected("<w:unsupported/>")),
        dict(body=paragraph("Before") + selected(p("<w:drawing/>"))),
        dict(body=paragraph("Before"), styles=selected(style("A") + style("A"))),
        dict(body=p(ref()), foot=selected(note("3"))),
        dict(body=paragraph("Before"), attrs='mc:MustUnderstand="x"'),
        dict(
            body=paragraph("Before"),
            extras={"other.bin": b"synthetic"},
            types={"other.bin": "application/octet-stream"},
        ),
        dict(body=selected(table(row(cell(paragraph("A"))), 2))),
        dict(body=selected("<w:p>" + simple(attrs=' w:dirty="true"') + "</w:p>")),
    ],
)
def test_active_unsupported_content_or_catalogs_never_return_partial_text(kwargs):
    raw, _ = fixture(**kwargs)
    s = build(raw)
    assert not s.complete and s.analysis_text == ""
    assert s.fragments == s.references == s.paragraphs == s.runs == ()
    assert any(c.status == "blocked" for c in s.coverage)
    assert api().map_compatibility_spans(raw, s, requests=()) == ()


def test_old_and_new_profiles_are_distinct_and_mutually_rejected():
    old = import_module("ara.docx_analysis.visible_control_tables")
    raw, _ = fixture(paragraph("Plain"))
    before = old.build_control_table_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    after = build(raw)
    assert before.complete and after.complete and before.analysis_text == after.analysis_text
    assert before.fragments[0].fragment_id != after.fragments[0].fragment_id
    error("invalid_snapshot", lambda: api().map_compatibility_spans(raw, before, requests=()))
    error("invalid_snapshot", lambda: old.map_control_table_spans(raw, after, requests=()))
    fake = rehash(replace(before, profile=PROFILE))
    error("invalid_snapshot", lambda: api().map_compatibility_spans(raw, fake, requests=()))
    mc = fixture(selected(paragraph("Selected")))[0]
    assert not old.build_control_table_snapshot(
        mc, document_id=DOC, storage_revision=7, source_sha256=sha256(mc).hexdigest()
    ).complete


def test_rehashed_changes_to_text_source_paths_and_context_do_not_authorize_mapping():
    raw, _ = fixture(selected(paragraph("Actual")))
    s = build(raw)
    f = s.fragments[0]
    for fake in [
        replace(s, complete=False),
        replace(s, coverage=()),
        replace(s, analysis_text="Fake"),
        replace(s, style_context=replace(s.style_context, context_sha256="0" * 64)),
        replace(
            s, fragments=(replace(f, pieces=(replace(f.pieces[0], anchor=f.paragraph_anchor),)),)
        ),
    ]:
        error(
            "invalid_snapshot",
            lambda fake=fake: api().map_compatibility_spans(raw, rehash(fake), requests=()),
        )
    other = fixture(selected(paragraph("Changed")))[0]
    error("source_mismatch", lambda: api().map_compatibility_spans(other, s, requests=()))
    error(
        "invalid_span",
        lambda: api().map_compatibility_span(
            raw, s, fragment_id=f.fragment_id, start=0, end=6, quote="Hidden"
        ),
    )
