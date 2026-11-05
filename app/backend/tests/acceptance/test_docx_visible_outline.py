"""Multilevel source numbering is context, never manufactured literal evidence."""

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
from test_docx_visible_lists import paragraph
from test_docx_visible_main import DOC, R, canonical, codes, payload, rehash
from test_docx_visible_plain_controls import plain, run
from test_docx_visible_unlisted import selected, source

PROFILE = "docx-analysis/final-visible-direct-outline-v1"


def api():
    return import_module("ara.docx_analysis.visible_outline")


def build(raw, **kw):
    return api().build_outline_snapshot(
        raw,
        **(dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()) | kw),
    )


def level(i, *, start=1, fmt="decimal", text=None, restart=None, legal=None, suffix=None):
    atoms = "" if start is None else f'<w:start w:val="{start}"/>'
    atoms += f'<w:numFmt w:val="{fmt}"/>'
    if restart is not None:
        atoms += f'<w:lvlRestart w:val="{restart}"/>'
    if legal is not None:
        atoms += f'<w:isLgl w:val="{legal}"/>'
    if suffix is not None:
        atoms += f'<w:suff w:val="{suffix}"/>'
    atoms += '<w:lvlText w:val="' + (text if text is not None else f"%{i + 1}.") + '"/>'
    return f'<w:lvl w:ilvl="{i}">' + atoms + "</w:lvl>"


def definitions(*levels, overrides="", extra="", kind="multilevel"):
    return (
        '<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="'
        + kind
        + '"/>'
        + "".join(levels or (level(0), level(1, text="%1.%2.")))
        + '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/>'
        + overrides
        + "</w:num>"
        + extra
    )


def sequence(levels, *, number=1):
    return "".join(paragraph(f"Text{i}😀", number, j) for i, j in enumerate(levels))


def original(raw, parts, s):
    requests = tuple(
        api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text) for f in s.fragments
    )
    for f, mapped in zip(
        s.fragments, api().map_outline_spans(raw, s, requests=requests), strict=True
    ):
        values = []
        for item in mapped.slices:
            node = resolve(ET.fromstring(parts[item.anchor.part_name]), item.anchor)
            value = node.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            values.append(value[item.start : item.end])
        assert "".join(values) == f.text
    for item in s.lists:
        for key, tag in (
            ("paragraph_anchor", "p"),
            ("properties_anchor", "numPr"),
            ("definition_anchor", "lvl"),
            ("instance_anchor", "num"),
        ):
            a = getattr(item, key)
            assert resolve(ET.fromstring(parts[a.part_name]), a).tag.endswith("}" + tag)
        if item.start_override_anchor is not None:
            a = item.start_override_anchor
            assert resolve(ET.fromstring(parts[a.part_name]), a).tag.endswith("}startOverride")


def error(code, call):
    with pytest.raises(api().VisibleViewError) as exc:
        call()
    assert exc.value.code == code


def blocked(raw):
    s = build(raw)
    assert not s.complete and s.analysis_text == "" and s.fragments == s.lists == s.references == ()
    assert ("excluded", "unused_numbering_definition") not in codes(s)
    return s


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_nested_numbers_keep_exact_source_and_restart_after_parent(strict, encoding):
    raw, parts = source(sequence([0, 1, 1, 0, 1]), definitions(), strict=strict, encoding=encoding)
    before = sha256(raw).hexdigest()
    s = build(raw)
    assert s.complete and type(s) is api().OutlineSnapshot and s.profile == PROFILE
    assert [x.label for x in s.lists] == ["1.", "1.1.", "1.2.", "2.", "2.1."]
    assert [x.level for x in s.lists] == [0, 1, 1, 0, 1]
    assert s.analysis_text == "\n\n".join(f"Text{i}😀" for i in range(5))
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and s == build(raw)
    original(raw, parts, s)
    assert sha256(raw).hexdigest() == before


@pytest.mark.parametrize(
    "restart,expected", [(None, [1, 1, 1]), (0, [1, 2, 3]), (1, [1, 2, 1]), (2, [1, 1, 1])]
)
def test_restart_trigger_includes_higher_events_and_zero_never_restarts(restart, expected):
    defs = definitions(level(0), level(1), level(2, restart=restart))
    s = build(source(sequence([0, 1, 2, 1, 2, 0, 1, 2]), defs)[0])
    assert s.complete and [x.ordinal for x in s.lists if x.level == 2] == expected
    skipped = build(source(sequence([2, 0, 2]), defs)[0])
    assert skipped.complete and [x.ordinal for x in skipped.lists if x.level == 2] == (
        [1, 2] if restart == 0 else [1, 1]
    )


def test_nine_levels_and_independent_instances_do_not_share_counters():
    defs = definitions(
        *(level(i) for i in range(9)),
        extra='<w:num w:numId="2"><w:abstractNumId w:val="0"/></w:num>',
    )
    raw, parts = source(
        sequence(range(9)) + paragraph("Other", 2, 8) + paragraph("Last", 1, 8), defs
    )
    s = build(raw)
    assert s.complete and [x.level for x in s.lists] == list(range(9)) + [8, 8]
    assert [x.ordinal for x in s.lists] == [1] * 10 + [2]
    original(raw, parts, s)


@pytest.mark.parametrize("start_override", [None, 7])
@pytest.mark.parametrize("restart", [None, 0])
def test_replacement_defaults_start_override_and_word_base_restart(start_override, restart):
    override = '<w:lvlOverride w:ilvl="1">'
    if start_override is not None:
        override += f'<w:startOverride w:val="{start_override}"/>'
    override += (
        level(1, start=None, text="%2)", restart=1 if restart == 0 else 0) + "</w:lvlOverride>"
    )
    defs = definitions(level(0), level(1, start=3, restart=restart), overrides=override)
    raw, parts = source(sequence([0, 1, 0, 1]), defs)
    s = build(raw)
    initial = 0 if start_override is None else start_override
    assert s.complete and [x.ordinal for x in s.lists if x.level == 1] == [
        initial,
        initial + (restart == 0),
    ]
    child = s.lists[1]
    node = resolve(ET.fromstring(parts[child.definition_anchor.part_name]), child.definition_anchor)
    assert any(
        n.tag.endswith("}lvlText") and n.attrib.get(node.tag.rpartition("}")[0] + "}val") == "%2)"
        for n in node
    )
    assert (child.start_override_anchor is not None) == (start_override is not None)
    original(raw, parts, s)


def test_override_for_a_different_level_is_not_applied():
    defs = definitions(
        overrides='<w:lvlOverride w:ilvl="1"><w:startOverride w:val="8"/></w:lvlOverride>'
    )
    s = build(source(sequence([0, 1, 0, 1]), defs)[0])
    assert s.complete and [x.label for x in s.lists] == ["1.", "1.8.", "2.", "2.8."]
    assert all(x.start_override_anchor is None for x in s.lists if x.level == 0)


@pytest.mark.parametrize(
    "start,expected",
    [
        (1, "I"),
        (4, "IV"),
        (9, "IX"),
        (40, "XL"),
        (90, "XC"),
        (400, "CD"),
        (900, "CM"),
        (3999, "MMMCMXCIX"),
        (4000, "MMMM"),
    ],
)
def test_roman_values_are_subtractive_and_not_excel_or_limited_to_3999(start, expected):
    defs = definitions(level(0, start=start, fmt="upperRoman", text="%1"))
    s = build(source(paragraph(), defs)[0])
    assert s.complete and s.lists[0].label == expected and s.lists[0].ordinal == start


@pytest.mark.parametrize(
    "legal,expected", [(None, "IV.ix"), ("0", "IV.ix"), ("1", "4.9"), ("on", "4.9")]
)
def test_parent_format_and_legal_decimal_override(legal, expected):
    defs = definitions(
        level(0, start=4, fmt="upperRoman"),
        level(1, start=9, fmt="lowerRoman", text="%1.%2", legal=legal),
    )
    s = build(source(sequence([0, 1]), defs)[0])
    assert s.complete and [x.label for x in s.lists] == ["IV.", expected]


@pytest.mark.parametrize("suffix", ["tab", "space", "nothing"])
def test_literal_bullet_percent_and_hidden_items_are_counted(suffix):
    defs = definitions(level(0, fmt="bullet", text="•%9😀", suffix=suffix))
    raw, parts = source(
        paragraph("")
        + paragraph(atoms="<w:rPr><w:vanish/></w:rPr><w:t>Secret</w:t>")
        + paragraph("Visible"),
        defs,
    )
    s = build(raw)
    assert s.complete and s.analysis_text == "Visible" and "Secret" not in repr(s)
    assert [x.ordinal for x in s.lists] == [1, 2, 3]
    assert all(x.label == "•%9😀" and x.suffix == suffix for x in s.lists)
    assert s.lists[0].fragment_ids == s.lists[1].fragment_ids == ()
    original(raw, parts, s)


@pytest.mark.parametrize("wrapper", [control, plain, selected])
def test_tables_gaps_and_selected_wrappers_preserve_single_consumption(wrapper):
    body = (
        paragraph("Parent")
        + "<w:p>"
        + run("Gap")
        + "</w:p>"
        + table(row(cell(wrapper(paragraph("Cell", level=1)))), 1)
        + paragraph("After", level=1)
    )
    raw, parts = source(body, definitions())
    s = build(raw)
    assert s.complete and [x.label for x in s.lists] == ["1.", "1.1.", "1.2."]
    assert [f.text for f in s.fragments] == ["Parent", "Gap", "Cell", "After"]
    original(raw, parts, s)


def test_raster_fragments_share_a_single_multilevel_marker():
    body = paragraph("Parent") + paragraph(
        level=1, atoms="<w:t>Before</w:t>" + drawing() + "<w:t>After</w:t>"
    )
    raw, parts = source(
        body,
        definitions(),
        extra_parts={IMAGE: png()},
        extra_types={IMAGE: "image/png"},
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "I", "Type": R + "image", "Target": "picture.bin"},
        ],
    )
    s = build(raw)
    assert s.complete and [x.label for x in s.lists] == ["1.", "1.1."]
    assert (
        s.lists[1].fragment_ids == tuple(f.fragment_id for f in s.fragments[1:])
        and len(s.lists[1].fragment_ids) == 2
    )
    original(raw, parts, s)


@pytest.mark.parametrize("text", ["%3", "%0", "%10", "%1x%", "%x", "%1" * 10])
def test_unproved_or_excessive_placeholder_forms_block_atomically(text):
    blocked(source(sequence([0, 1]), definitions(level(0), level(1, text=text)))[0])


@pytest.mark.parametrize("fmt", ["upperLetter", "lowerLetter", "none"])
def test_language_dependent_and_unproved_formats_are_explicit_gates(fmt):
    blocked(source(paragraph("Private"), definitions(level(0, fmt=fmt)))[0])


def test_unknown_or_reset_parent_and_bullet_reference_never_invent_a_number():
    blocked(source(paragraph(level=1), definitions())[0])
    defs = definitions(level(0), level(1), level(2, text="%2.%3"))
    blocked(source(sequence([1, 2, 0, 2]), defs)[0])
    defs = definitions(level(0, fmt="bullet", text="•"), level(1, text="%1.%2"))
    blocked(source(sequence([0, 1]), defs)[0])


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.replace('<w:lvlText w:val="%1."/>', ""),
        lambda d: d.replace('<w:lvlText w:val="%1."/>', '<w:lvlText w:val="%1." w:null="1"/>'),
        lambda d: d.replace("</w:lvl>", "<w:rPr><w:vanish/></w:rPr></w:lvl>", 1),
        lambda d: d.replace("<w:lvlText", '<w:lvlRestart w:val="8"/><w:lvlText', 1),
        lambda d: d.replace('w:numId="1"', 'w:numId="9"'),
        lambda d: d.replace("</w:abstractNum>", '<w:styleLink w:val="Unknown"/></w:abstractNum>'),
    ],
)
def test_malformed_or_unresolved_source_does_not_silently_drop_labels(change):
    blocked(source(sequence([0, 1]), change(definitions()))[0])


def test_counter_overflow_and_roman_zero_refuse_all_text():
    s = blocked(source(sequence([0, 0]), definitions(level(0, start=2147483647)))[0])
    assert any(c.code == "list_counter_overflow" for c in s.coverage)
    blocked(source(paragraph(), definitions(level(0, start=0, fmt="upperRoman")))[0])


@pytest.mark.parametrize(
    "fmt,start,text",
    [("upperRoman", 2147483647, "%1"), ("decimal", 1, "X" * 32), ("bullet", 1, "😀" * 16)],
)
def test_label_expansion_is_bounded_before_large_allocation(fmt, start, text):
    raw = source(paragraph(), definitions(level(0, fmt=fmt, start=start, text=text)))[0]
    error("view_limit_exceeded", lambda: build(raw))


def test_literal_and_generated_characters_share_the_document_budget():
    raw = source(paragraph("A"), definitions(level(0, text="123456789")))[0]
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_text_characters=10)),
    )
    s = build(raw, limits=api().VisibleLimits(max_text_characters=11))
    assert s.complete and s.analysis_text == "A"


def test_numid_zero_and_spanning_field_boundaries_keep_old_safety_rules():
    s = build(source(paragraph("Plain", number=0, level=8), definitions())[0])
    assert s.complete and s.lists == () and s.analysis_text == "Plain"
    body = paragraph(atoms=char("begin") + instr("PRIVATE")) + paragraph(
        level=1, atoms=char("separate") + "<w:t>Result</w:t>" + char("end")
    )
    s = blocked(source(body, definitions())[0])
    assert any(c.code == "unsupported_list_field_boundary" for c in s.coverage)


def test_source_identity_mapping_and_rehashed_forgery_require_original_proof():
    raw, _ = source(sequence([0, 1]), definitions())
    s = build(raw)
    f = s.fragments[1]
    m = api().map_outline_span(
        raw, s, fragment_id=f.fragment_id, start=0, end=len(f.text), quote=f.text
    )
    assert m.slices
    error("source_mismatch", lambda: build(raw, source_sha256="0" * 64))
    for changed in (
        replace(s.lists[1], label="99"),
        replace(s.lists[1], ordinal=99),
        replace(s.lists[1], level=0),
        replace(s.lists[1], definition_anchor=s.lists[0].definition_anchor),
        replace(s.lists[1], fragment_ids=()),
        replace(s.lists[1], level=True),
    ):
        forged = rehash(replace(s, lists=(s.lists[0], changed)))
        error("invalid_snapshot", lambda: api().map_outline_spans(raw, forged, requests=()))


def test_previous_profile_dtos_and_reader_are_not_silently_widened():
    from ara.docx_analysis.visible_lists import build_list_snapshot, map_list_spans

    raw = source(sequence([0, 1]), definitions())[0]
    old = build_list_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not old.complete and old.lists == ()
    s = build(raw)
    error("invalid_snapshot", lambda: map_list_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_outline_spans(raw, old, requests=()))


@pytest.mark.parametrize("restart,expected", [(None, [1, 1, 1]), (7, [1, 2, 1])])
def test_last_level_default_and_explicit_restart_are_distinct(restart, expected):
    defs = definitions(*(level(i, restart=restart if i == 8 else None) for i in range(9)))
    s = build(source(sequence([8, 7, 8, 6, 8]), defs)[0])
    assert s.complete and [x.ordinal for x in s.lists if x.level == 8] == expected


@pytest.mark.parametrize("numbered_note", [False, True])
def test_referenced_note_keeps_literal_mapping_but_numbering_story_stays_gated(numbered_note):
    from test_docx_note_catalog import note
    from test_docx_section_catalog import BASE
    from test_docx_visible_notes import literal, note_xml, p, ref

    foot = paragraph("Foot") if numbered_note else p("<w:footnoteRef/>" + literal("Foot"))
    raw, parts = source(
        paragraph("Parent")
        + paragraph(level=1, atoms=literal("Before") + ref() + literal("After")),
        definitions(),
        extra_parts={"custom/Foot.xml": note_xml(note("2", content=foot))},
        extra_types={"custom/Foot.xml": BASE + "footnotes+xml"},
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    if numbered_note:
        s = blocked(raw)
        assert any(c.code == "unsupported_list_story" for c in s.coverage)
    else:
        s = build(raw)
        assert s.complete and len(s.references) == 1
        assert [x.label for x in s.lists] == ["1.", "1.1."]
        assert [f.text for f in s.fragments] == ["Parent", "Before", "After", "Foot"]
        original(raw, parts, s)


@pytest.mark.parametrize("maximum", ["max_xml_nodes", "max_xml_depth", "max_xml_characters"])
def test_raw_bounds_fire_before_selected_context_dom(monkeypatch, maximum):
    module = import_module("ara.docx_analysis.visible_outline._api")

    def forbidden(*args, **kwargs):
        raise AssertionError("selected DOM must not precede raw bounds")

    monkeypatch.setattr(module, "prepare", forbidden)
    raw = source(sequence([0, 1]), definitions())[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(**{maximum: 1})))


def test_source_change_and_mismatched_literal_quote_cannot_map():
    raw = source(sequence([0, 1]), definitions())[0]
    s = build(raw)
    changed = source(sequence([0, 1]) + paragraph("Changed"), definitions())[0]
    error("source_mismatch", lambda: api().map_outline_spans(changed, s, requests=()))
    f = s.fragments[0]
    error(
        "invalid_span",
        lambda: api().map_outline_span(
            raw, s, fragment_id=f.fragment_id, start=0, end=len(f.text), quote="Wrong text"
        ),
    )
    error(
        "view_limit_exceeded",
        lambda: api().map_outline_spans(
            raw, s, requests=(), limits=api().VisibleLimits(max_manifest_bytes=1)
        ),
    )
