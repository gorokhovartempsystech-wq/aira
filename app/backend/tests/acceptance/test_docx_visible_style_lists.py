"""Style-generated labels keep their physical provenance and literal source evidence."""

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
from test_docx_visible_lists import paragraph
from test_docx_visible_main import DOC, R, S, W, canonical, payload, rehash, style
from test_docx_visible_outline import definitions, level
from test_docx_visible_plain_controls import plain, run
from test_docx_visible_unlisted import selected, source

PROFILE = "docx-analysis/final-visible-style-lists-v1"
STYLE_PROFILE = "docx-visibility/mc-style-numbering-v1"


def api():
    return import_module("ara.docx_analysis.visible_style_lists")


def build(raw, **kw):
    return api().build_style_list_snapshot(
        raw,
        **(dict(document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()) | kw),
    )


def bound_level(i, key, **kw):
    value = level(i, **kw)
    pos = min(value.index(tag) for tag in ("<w:isLgl", "<w:suff", "<w:lvlText") if tag in value)
    return value[:pos] + f'<w:pStyle w:val="{key}"/>' + value[pos:]


def numbered_style(key, number=1, *, base=None, default=False, extra="", kind="paragraph"):
    props = "" if base is None else f'<w:basedOn w:val="{base}"/>'
    if number is not None:
        props += f'<w:pPr><w:numPr><w:numId w:val="{number}"/></w:numPr></w:pPr>'
    return style(key, props + extra, kind, 'w:default="1"' if default else "")


def styled(text="Text😀Я", key="S0", *, direct=None, atoms=None):
    props = "" if key is None else f'<w:pStyle w:val="{key}"/>'
    props += direct or ""
    return (
        "<w:p>"
        + ("<w:pPr>" + props + "</w:pPr>" if props else "")
        + (run(text) if atoms is None else "<w:r>" + atoms + "</w:r>")
        + "</w:p>"
    )


def fixture(body=None, defs=None, styles=None, **kw):
    return source(
        styled() if body is None else body,
        definitions(bound_level(0, "S0"), bound_level(1, "S1", text="%1.%2."))
        if defs is None
        else defs,
        styles=numbered_style("S0") + numbered_style("S1") if styles is None else styles,
        **kw,
    )


def repack(parts):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for key, value in parts.items():
            z.writestr(key, value)
    return out.getvalue()


def error(code, call):
    with pytest.raises(api().VisibleViewError) as exc:
        call()
    assert exc.value.code == code


def blocked(raw):
    s = build(raw)
    assert not s.complete and s.analysis_text == "" and s.fragments == s.lists == s.references == ()
    return s


def original(raw, parts, s):
    requests = tuple(
        api().VisibleSpanRequest(f.fragment_id, 0, len(f.text), f.text) for f in s.fragments
    )
    for f, mapped in zip(
        s.fragments, api().map_style_list_spans(raw, s, requests=requests), strict=True
    ):
        values = []
        for item in mapped.slices:
            node = resolve(ET.fromstring(parts[item.anchor.part_name]), item.anchor)
            value = node.text if item.kind == "text" else "\t" if item.kind == "tab" else "\n"
            values.append(value[item.start : item.end])
        assert "".join(values) == f.text
    for item in s.lists:
        assert type(item) is api().StyleListItem
        checks = [
            (item.paragraph_anchor, "p"),
            (item.properties_anchor, "numPr"),
            (item.definition_anchor, "lvl"),
            (item.instance_anchor, "num"),
        ]
        checks += [(a, "style") for a in item.style_chain]
        checks += [
            (a, tag)
            for a, tag in (
                (item.start_override_anchor, "startOverride"),
                (item.style_reference_anchor, "pStyle"),
                (item.level_style_anchor, "pStyle"),
            )
            if a is not None
        ]
        for a, tag in checks:
            assert a.source_sha256 == sha256(raw).hexdigest()
            assert resolve(ET.fromstring(parts[a.part_name]), a).tag.endswith("}" + tag)
        if item.numbering_source == "style":
            assert item.properties_anchor.part_name == "custom/Styles.xml"
            assert (
                item.properties_anchor.path[: len(item.style_chain[-1].path)]
                == item.style_chain[-1].path
            )
        else:
            assert item.numbering_source == "direct" and item.style_chain == ()
            assert item.style_reference_anchor is item.level_style_anchor is None


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_direct_and_style_items_share_counters_and_keep_physical_source(strict, encoding):
    body = styled("Parent") + paragraph("Direct child", level=1) + styled("Styled child", "S1")
    body += paragraph("Direct parent") + styled("Restarted child", "S1")
    raw, parts = fixture(body, strict=strict, encoding=encoding)
    before = sha256(raw).hexdigest()
    s = build(raw)
    assert s.complete and type(s) is api().StyleListSnapshot and s.profile == PROFILE
    assert s.style_context.profile == STYLE_PROFILE
    assert [x.label for x in s.lists] == ["1.", "1.1.", "1.2.", "2.", "2.1."]
    assert [x.numbering_source for x in s.lists] == ["style", "direct", "style", "direct", "style"]
    assert (
        s.analysis_text
        == "Parent\n\nDirect child\n\nStyled child\n\nDirect parent\n\nRestarted child"
    )
    assert s.snapshot_sha256 == sha256(canonical(payload(s))).hexdigest() and s == build(raw)
    original(raw, parts, s)
    assert sha256(raw).hexdigest() == before


@pytest.mark.parametrize("implicit", [False, True])
def test_inherited_numid_requires_applied_style_binding_and_records_chain(implicit):
    styles = numbered_style("Base") + numbered_style("Middle", None, base="Base")
    styles += numbered_style("Child", None, base="Middle", default=implicit)
    raw, parts = fixture(
        styled(key=None if implicit else "Child"), definitions(bound_level(0, "Child")), styles
    )
    s = build(raw)
    assert s.complete and [x.label for x in s.lists] == ["1."]
    item = s.lists[0]
    assert len(item.style_chain) == 3 and (item.style_reference_anchor is None) == implicit
    root = ET.fromstring(parts["custom/Styles.xml"])
    assert [resolve(root, a).get("{" + W + "}styleId") for a in item.style_chain] == [
        "Child",
        "Middle",
        "Base",
    ]
    original(raw, parts, s)


@pytest.mark.parametrize("number", [0, 2])
def test_nearest_style_numid_overrides_ancestor_without_using_ancestor_binding(number):
    defs = definitions(
        bound_level(0, "Child"), extra='<w:num w:numId="2"><w:abstractNumId w:val="0"/></w:num>'
    )
    styles = numbered_style("Base") + numbered_style("Child", number, base="Base")
    raw, parts = fixture(styled(key="Child"), defs, styles)
    s = build(raw)
    assert s.complete and s.analysis_text == "Text😀Я"
    if number == 0:
        assert s.lists == ()
    else:
        assert [x.num_id for x in s.lists] == [2] and len(s.lists[0].style_chain) == 1
    original(raw, parts, s)


@pytest.mark.parametrize("number", [0, 2])
def test_explicit_direct_properties_win_and_zero_does_not_consume(number):
    defs = definitions(
        bound_level(0, "S0"), extra='<w:num w:numId="2"><w:abstractNumId w:val="0"/></w:num>'
    )
    direct = f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{number}"/></w:numPr>'
    raw, parts = fixture(styled("First") + styled("Override", direct=direct) + styled("Last"), defs)
    s = build(raw)
    assert s.complete and [x.num_id for x in s.lists] == ([1, 1] if number == 0 else [1, 2, 1])
    assert [x.ordinal for x in s.lists] == ([1, 2] if number == 0 else [1, 1, 2])
    original(raw, parts, s)


@pytest.mark.parametrize("wrapper", [control, plain, selected])
def test_table_wrappers_blank_and_hidden_items_keep_one_marker_each(wrapper):
    body = styled("") + styled(atoms="<w:rPr><w:vanish/></w:rPr><w:t>PRIVATE</w:t>")
    body += table(row(cell(wrapper(styled("Visible")))), 1)
    raw, parts = fixture(body)
    s = build(raw)
    assert s.complete and s.analysis_text == "Visible" and "PRIVATE" not in repr(s)
    assert [x.ordinal for x in s.lists] == [1, 2, 3]
    assert s.lists[0].fragment_ids == s.lists[1].fragment_ids == ()
    original(raw, parts, s)


def test_selected_style_properties_use_original_wrapper_paths():
    raw, parts = fixture(styles=selected(numbered_style("S0")))
    s = build(raw)
    assert s.complete and len(s.lists[0].style_chain[0].path) > 1
    original(raw, parts, s)


def test_styles_part_uses_its_actual_namespace():
    _, parts = fixture()
    parts["custom/Styles.xml"] = parts["custom/Styles.xml"].replace(W.encode(), S.encode())
    raw = repack(parts)
    s = build(raw)
    assert s.complete and [x.label for x in s.lists] == ["1."]
    original(raw, parts, s)


def test_replacement_level_uses_abstract_binding_and_start_override():
    override = (
        '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="4"/>'
        + level(0, fmt="upperRoman", text="%1)")
        + "</w:lvlOverride>"
    )
    raw, parts = fixture(defs=definitions(bound_level(0, "S0"), overrides=override))
    s = build(raw)
    assert s.complete and [x.label for x in s.lists] == ["IV)"]
    assert s.lists[0].start_override_anchor is not None
    assert s.lists[0].level_style_anchor.path[:-1] != s.lists[0].definition_anchor.path
    original(raw, parts, s)


@pytest.mark.parametrize("numbered", [False, True])
def test_note_literal_is_retained_but_numbered_note_stays_gated(numbered):
    from test_docx_note_catalog import note
    from test_docx_section_catalog import BASE
    from test_docx_visible_notes import literal, note_xml, p, ref

    foot = styled("Foot") if numbered else p("<w:footnoteRef/>" + literal("Foot"))
    raw, parts = fixture(
        styled(atoms=literal("Before") + ref() + literal("After")),
        extra_parts={"custom/Foot.xml": note_xml(note("2", content=foot))},
        extra_types={"custom/Foot.xml": BASE + "footnotes+xml"},
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    if numbered:
        s = blocked(raw)
        assert any(c.code == "unsupported_list_story" for c in s.coverage)
    else:
        s = build(raw)
        assert s.complete and len(s.lists) == len(s.references) == 1
        assert [f.text for f in s.fragments] == ["Before", "After", "Foot"]
        original(raw, parts, s)


@pytest.mark.parametrize(
    "styles",
    [
        numbered_style("S0", None, base="Missing"),
        numbered_style("S0", None, base="S1") + numbered_style("S1", None, base="S0"),
        numbered_style("S0", None, base="C") + style("C", kind="character"),
        numbered_style("Different"),
        style("S0", kind="character"),
    ],
)
def test_missing_cyclic_wrong_type_or_unresolved_style_refuses_all_text(styles):
    blocked(fixture(styles=styles)[0])


@pytest.mark.parametrize(
    "defs,styles",
    [
        (definitions(level(0)), numbered_style("S0")),
        (
            definitions(bound_level(0, "Base")),
            numbered_style("Base") + numbered_style("S0", None, base="Base"),
        ),
        (definitions(bound_level(0, "S0"), bound_level(1, "S0")), numbered_style("S0")),
        (definitions(bound_level(0, "S0")), numbered_style("S0", 99)),
    ],
)
def test_absent_ambiguous_or_ancestor_only_binding_is_not_guessed(defs, styles):
    blocked(fixture(defs=defs, styles=styles)[0])


@pytest.mark.parametrize(
    "numpr",
    [
        '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>',
        '<w:numPr><w:numId w:val="1"/><w:numId w:val="1"/></w:numPr>',
        "<w:numPr/>",
        '<w:numPr x="1"><w:numId w:val="1"/></w:numPr>',
        '<w:numPr><w:numId w:val="-1"/></w:numPr>',
        '<w:numPr><w:numId w:val="2147483648"/></w:numPr>',
        '<w:numPr><w:numId w:val="1"/><w:ins w:id="1"/></w:numPr>',
    ],
)
def test_style_numpr_is_closed_and_does_not_guess_word_ilvl_behavior(numpr):
    blocked(fixture(styles=style("S0", "<w:pPr>" + numpr + "</w:pPr>"))[0])


@pytest.mark.parametrize(
    "numpr", ['<w:numPr><w:numId w:val="1"/></w:numPr>', '<w:numPr><w:ilvl w:val="0"/></w:numPr>']
)
def test_partial_direct_properties_do_not_merge_with_style(numpr):
    blocked(fixture(styled(direct=numpr))[0])


@pytest.mark.parametrize("origin", ["defaults", "table"])
def test_unproved_defaults_and_table_style_numbering_do_not_get_silently_lost(origin):
    numpr = '<w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr>'
    if origin == "defaults":
        styles = "<w:docDefaults><w:pPrDefault>" + numpr + "</w:pPrDefault></w:docDefaults>"
        raw = fixture(styled(key=None), styles=styles)[0]
    else:
        styles = style("T", numpr, kind="table", attrs='w:default="1"')
        raw = fixture(table(row(cell(styled(key=None))), 1), styles=styles)[0]
    blocked(raw)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.replace('<w:pStyle w:val="S0"/>', '<w:pStyle w:val=""/>'),
        lambda d: d.replace('<w:pStyle w:val="S0"/>', '<w:pStyle w:val="S0" x="1"/>'),
        lambda d: d.replace("</w:abstractNum>", '<w:numStyleLink w:val="S0"/></w:abstractNum>'),
        lambda d: d.replace("</w:abstractNum>", '<w:styleLink w:val="S0"/></w:abstractNum>'),
    ],
)
def test_definition_grammar_preserves_closed_link_and_identity_guards(change):
    blocked(fixture(defs=change(definitions(bound_level(0, "S0"))))[0])


def test_replacement_pstyle_is_not_treated_as_abstract_association():
    defs = definitions(
        bound_level(0, "S0"),
        overrides='<w:lvlOverride w:ilvl="0">' + bound_level(0, "S0") + "</w:lvlOverride>",
    )
    blocked(fixture(defs=defs)[0])


def test_style_selection_is_attached_before_cross_paragraph_field_guard():
    body = styled(atoms=char("begin") + instr("PRIVATE"))
    body += styled(atoms=char("separate") + "<w:t>Result</w:t>" + char("end"))
    s = blocked(fixture(body)[0])
    assert any(c.code == "unsupported_list_field_boundary" for c in s.coverage)


def test_unused_bindings_and_unlisted_style_do_not_create_generated_markers():
    raw, parts = fixture(styled("Plain", "Plain"), styles=numbered_style("Plain", None))
    s = build(raw)
    assert s.complete and s.lists == () and s.analysis_text == "Plain"
    original(raw, parts, s)


@pytest.mark.parametrize("maximum", ["max_xml_nodes", "max_xml_depth", "max_xml_characters"])
def test_raw_bounds_fire_before_selected_context_dom(monkeypatch, maximum):
    module = import_module("ara.docx_analysis.visible_style_lists._api")

    def forbidden(*args, **kw):
        raise AssertionError("raw bounds must precede selected DOM")

    monkeypatch.setattr(module, "prepare", forbidden)
    raw = fixture()[0]
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(**{maximum: 1})))


def test_chain_and_combined_literal_label_budgets_are_enforced():
    from ara.docx_analysis.visibility import StyleContextLimits

    raw = fixture(styles=numbered_style("Base") + numbered_style("S0", None, base="Base"))[0]
    error(
        "view_limit_exceeded",
        lambda: build(
            raw, limits=api().VisibleLimits(styles=StyleContextLimits(max_chain_depth=1))
        ),
    )
    raw = fixture(styled("A"), definitions(bound_level(0, "S0", text="123456789")))[0]
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().VisibleLimits(max_text_characters=10)),
    )
    assert build(raw, limits=api().VisibleLimits(max_text_characters=11)).complete


def test_mapping_rebuild_rejects_every_rehashed_style_provenance_forgery():
    raw, _ = fixture(styles=numbered_style("Base") + numbered_style("S0", None, base="Base"))
    s = build(raw)
    item = s.lists[0]
    for changed in (
        replace(item, numbering_source="direct"),
        replace(item, numbering_source="anything"),
        replace(item, style_reference_anchor=None),
        replace(item, style_chain=()),
        replace(item, style_chain=tuple(reversed(item.style_chain))),
        replace(item, style_chain=(item.style_chain[0],) * 2),
        replace(item, properties_anchor=item.paragraph_anchor),
        replace(item, level_style_anchor=None),
        replace(item, level_style_anchor=item.definition_anchor),
        replace(item, label="99"),
        replace(item, ordinal=99),
        replace(item, level=True),
    ):
        forged = rehash(replace(s, lists=(changed,)))
        error("invalid_snapshot", lambda: api().map_style_list_spans(raw, forged, requests=()))
    f = s.fragments[0]
    assert (
        api()
        .map_style_list_span(
            raw, s, fragment_id=f.fragment_id, start=0, end=len(f.text), quote=f.text
        )
        .slices
    )
    error(
        "invalid_span",
        lambda: api().map_style_list_span(
            raw, s, fragment_id=f.fragment_id, start=0, end=len(f.text), quote="Wrong"
        ),
    )
    error(
        "source_mismatch",
        lambda: api().map_style_list_spans(fixture(styled("Other"))[0], s, requests=()),
    )


def test_old_reader_and_exact_profile_types_are_not_widened():
    from ara.docx_analysis.visible_outline import build_outline_snapshot, map_outline_spans

    raw = fixture()[0]
    old = build_outline_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    assert not old.complete and old.lists == ()
    s = build(raw)
    error("invalid_snapshot", lambda: map_outline_spans(raw, s, requests=()))
    error("invalid_snapshot", lambda: api().map_style_list_spans(raw, old, requests=()))


@pytest.mark.parametrize(
    "fmt,text,expected",
    [("upperRoman", "%1.", "IV."), ("lowerRoman", "%1.", "iv."), ("bullet", "•%9", "•%9")],
)
def test_all_outline_formats_remain_source_bound_under_styles(fmt, text, expected):
    raw, parts = fixture(defs=definitions(bound_level(0, "S0", start=4, fmt=fmt, text=text)))
    s = build(raw)
    assert s.complete and [x.label for x in s.lists] == [expected]
    original(raw, parts, s)


def test_all_nine_style_levels_and_legal_rendering_share_the_proven_counter_policy():
    styles = "".join(numbered_style("S" + str(i)) for i in range(9))
    defs = definitions(
        *(
            bound_level(
                i,
                "S" + str(i),
                fmt="upperRoman" if i == 0 else "decimal",
                start=4 if i == 0 else 1,
                text="%1.%2",
                legal="1",
            )
            if i == 1
            else bound_level(
                i, "S" + str(i), fmt="upperRoman" if i == 0 else "decimal", start=4 if i == 0 else 1
            )
            for i in range(9)
        )
    )
    raw, parts = fixture("".join(styled(str(i), "S" + str(i)) for i in range(9)), defs, styles)
    s = build(raw)
    assert s.complete and [x.level for x in s.lists] == list(range(9))
    assert [x.label for x in s.lists[:2]] == ["IV.", "4.1"]
    original(raw, parts, s)


def test_repeated_inherited_chains_have_an_aggregate_budget_even_when_cached():
    styles = numbered_style("Base")
    for i in range(1, 10):
        styles += numbered_style("S" + str(i), None, base="Base" if i == 1 else "S" + str(i - 1))
    raw = fixture(styled("A", "S9") * 50, definitions(bound_level(0, "S9")), styles)[0]
    assert len(build(raw).lists) == 50
    # This budget is above the raw XML node count, but below the 500 chain entries.
    error("view_limit_exceeded", lambda: build(raw, limits=api().VisibleLimits(max_xml_nodes=400)))


def test_previous_properties_do_not_supply_current_style_numbering():
    history = (
        '<w:pPr><w:pPrChange w:id="1"><w:pPr><w:numPr><w:ilvl w:val="0"/>'
        '<w:numId w:val="1"/></w:numPr></w:pPr></w:pPrChange></w:pPr>'
    )
    raw, parts = fixture(styles=style("S0", history))
    s = build(raw)
    assert s.complete and s.lists == ()
    original(raw, parts, s)


@pytest.mark.parametrize("change", ["unlinked", "wrong_namespace", "outgoing"])
def test_style_selection_keeps_numbering_relationship_guards(change):
    kw = {}
    if change == "unlinked":
        kw["links"] = []
    if change == "outgoing":
        from docx_package_fixtures import relationships_xml

        kw["extra_parts"] = {
            "custom/_rels/Numbers.xml.rels": relationships_xml(
                [
                    {
                        "Id": "X",
                        "Type": R + "hyperlink",
                        "Target": "https://example.invalid",
                        "TargetMode": "External",
                    }
                ]
            )
        }
    raw, parts = fixture(**kw)
    if change == "wrong_namespace":
        parts["custom/Numbers.xml"] = parts["custom/Numbers.xml"].replace(W.encode(), S.encode())
        raw = repack(parts)
    blocked(raw)


def test_no_styles_direct_snapshot_retains_outline_provenance_values():
    from dataclasses import fields

    from ara.docx_analysis.visible_lists import ListItem
    from ara.docx_analysis.visible_outline import build_outline_snapshot

    raw = source(paragraph("A") + paragraph("B", level=1), definitions())[0]
    old = build_outline_snapshot(
        raw, document_id=DOC, storage_revision=7, source_sha256=sha256(raw).hexdigest()
    )
    new = build(raw)
    assert new.complete and old.complete and new.analysis_text == old.analysis_text
    for before, after in zip(old.lists, new.lists, strict=True):
        for f in fields(ListItem):
            if f.name != "fragment_ids":
                assert getattr(before, f.name) == getattr(after, f.name)
        assert after.numbering_source == "direct" and after.style_chain == ()
