"""One selected source view for styles, sections and note metadata, not text admission."""

import json
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_compatibility_catalog import MAIN, MC, X, alternate, choice
from test_docx_compatibility_catalog import source as mc_source
from test_docx_move_catalog import resolve
from test_docx_note_catalog import note
from test_docx_section_catalog import BASE, boundary, previous, reference, section
from test_docx_table_styles import table_style
from test_docx_visibility_styles import style
from test_docx_visible_main import SR, R, S, W
from test_docx_visible_main import source as base_source

PROFILES = (
    "docx-visibility/mc-styles-context-v1",
    "docx-table-styles/mc-neutrality-v1",
    "docx-sections/mc-current-references-v1",
    "docx-notes/mc-definitions-v1",
)


def api():
    return import_module("ara.docx_analysis.compatibility_contexts")


def part_xml(root, content="", *, strict=False, encoding="utf-8", attrs=""):
    w, r = (S, SR) if strict else (W, R)
    return (
        f'<?xml version="1.0" encoding="{encoding}"?><w:{root} xmlns:w="{w}" '
        f'xmlns:r="{r[:-1]}" xmlns:mc="{MC}" xmlns:x="{X}" {attrs}>' + content + f"</w:{root}>"
    ).encode(encoding)


def fixture(
    body="<w:p/>",
    *,
    styles=None,
    settings=None,
    foot=None,
    end=None,
    header=None,
    strict=False,
    encoding="utf-8",
    attrs="",
    extras=None,
    types=None,
    links=None,
):
    parts = {MAIN: mc_source(body, attrs, strict=strict, encoding=encoding)[1]}
    content_types, relationships = {}, []
    for kind, root, filename, content in (
        ("styles", "styles", "Styles", styles),
        ("settings", "settings", "Settings", settings),
        ("footnotes", "footnotes", "Foot", foot),
        ("endnotes", "endnotes", "End", end),
        ("header", "hdr", "H", header),
    ):
        if content is not None:
            name = f"custom/{filename}.xml"
            parts[name] = part_xml(root, content, strict=strict, encoding=encoding)
            content_types[name] = BASE + kind + "+xml"
            relationships.append(
                {"Id": filename, "Type": (SR if strict else R) + kind, "Target": filename + ".xml"}
            )
    parts.update(extras or {})
    content_types.update(types or {})
    raw = base_source(
        "",
        strict=strict,
        encoding=encoding,
        extra_parts=parts,
        extra_types=content_types,
        links=relationships if links is None else links,
    )[0]
    return raw, parts


def read(raw, **kw):
    return api().read_compatibility_contexts(raw, source_sha256=sha256(raw).hexdigest(), **kw)


def catalogs(c):
    return c.styles, c.table_styles, c.sections, c.notes


def digest(c, key):
    values = asdict(c)
    values.pop(key)
    return sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def blocked(raw):
    c = read(raw)
    assert c.status == "blocked" and catalogs(c) == (None,) * 4 and len(c.issues) == 1
    return c


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_same_id_alternatives_select_one_style_and_original_property_anchors(strict, encoding):
    content = alternate(
        choice("x", style("A", kind="character"))
        + choice("w", style("A", "<w:rPr><w:vanish/></w:rPr>", kind="character"))
    )
    raw, parts = fixture(styles=content, strict=strict, encoding=encoding)
    c = read(raw)
    assert (
        c.status == "ready"
        and c.profile == "docx-compatibility/selected-contexts-v1"
        and c.issues == ()
    )
    assert tuple(x.profile for x in catalogs(c)) == PROFILES
    assert all(x.source_sha256 == sha256(raw).hexdigest() for x in catalogs(c))
    assert len(c.styles.styles) == 1 and c.styles.styles[0].style_id == "A"
    s = c.styles.styles[0]
    assert s.status == "resolved" and s.properties.vanish.value is True
    assert s.anchor.path == (0, 1, 0) and s.properties.vanish.anchor.path == (0, 1, 0, 0, 0)
    assert resolve(
        ET.fromstring(parts["custom/Styles.xml"]), s.properties.vanish.anchor
    ).tag.endswith("}vanish")
    assert c.table_styles.style_context_sha256 == c.styles.context_sha256
    for obj, key in zip(
        catalogs(c), ("context_sha256", "catalog_sha256", "catalog_sha256", "catalog_sha256")
    ):
        assert getattr(obj, key) == digest(obj, key)
    assert read(raw) == c and not hasattr(c, "complete") and not hasattr(c, "analysis_text")
    with pytest.raises(FrozenInstanceError):
        c.status = "changed"
    assert not hasattr(c, "__dict__")


def test_selected_defaults_and_based_on_use_the_same_selected_style_graph():
    defaults = (
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>"
    )
    a = style("A", '<w:rPr><w:vanish w:val="false"/></w:rPr>', kind="character")
    b = style("B", '<w:basedOn w:val="A"/>', kind="character")
    content = alternate(choice("x", "<w:docDefaults/>") + choice("w", defaults + a + b))
    c = read(fixture(styles=content)[0])
    assert c.status == "ready" and c.styles.defaults.vanish.value is True
    records = {s.style_id: s for s in c.styles.styles}
    assert records["B"].based_on == "A" and records["B"].properties.vanish.value is False
    assert records["B"].properties.vanish.anchor == records["A"].properties.vanish.anchor
    assert c.styles.defaults.vanish.anchor.path == (0, 1, 0, 0, 0, 0)


def test_selected_table_styles_keep_neutrality_chain_regions_and_context_hash():
    base = table_style("Base", "<w:rPr><w:b/></w:rPr>", attrs='w:default="true"')
    child = table_style(
        "Child",
        '<w:basedOn w:val="Base"/><w:tblStylePr w:type="firstRow">'
        "<w:rPr><w:i/></w:rPr></w:tblStylePr>",
    )
    bad = table_style("Base", "<w:rPr><w:vanish/></w:rPr>")
    c = read(fixture(styles=alternate(choice("x", bad) + choice("w", base + child)))[0])
    assert c.status == "ready" and c.table_styles.default_table_style == "Base"
    base, child = c.table_styles.styles
    assert base.status == child.status == "neutral" and child.based_on == "Base"
    assert [a.path for a in child.chain] == [(0, 1, 1), (0, 1, 0)]
    assert child.regions[0].kind == "firstRow" and child.regions[0].anchor.path == (0, 1, 1, 1)
    assert c.table_styles.style_context_sha256 == c.styles.context_sha256


def test_selected_non_neutral_table_style_stays_blocked_per_definition():
    c = read(
        fixture(styles=alternate(choice("w", table_style("A", "<w:rPr><w:vanish/></w:rPr>"))))[0]
    )
    assert c.status == "ready" and c.table_styles.styles[0].status == "blocked"
    assert c.table_styles.styles[0].chain == () and c.table_styles.styles[0].metadata == ()


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_selected_settings_and_section_references_inherit_actual_original_anchors(strict, encoding):
    body = (
        boundary(
            alternate(
                choice("x", section(reference("Missing"))) + choice("w", section(reference("H")))
            )
        )
        + section()
    )
    settings = alternate(
        choice("x", '<w:evenAndOddHeaders w:val="false"/>') + choice("w", "<w:evenAndOddHeaders/>")
    )
    raw, parts = fixture(body, settings=settings, header="<w:p/>", strict=strict, encoding=encoding)
    c = read(raw)
    assert c.status == "ready" and c.sections.even_and_odd is True and len(c.sections.sections) == 2
    first, last = c.sections.sections
    assert first.anchor.path == (0, 0, 0, 0, 1, 0) and first.paragraph_anchor.path == (0, 0)
    assert first.references[0].anchor.path == (0, 0, 0, 0, 1, 0, 0)
    assert last.bindings[0].definition_anchor == first.references[0].anchor
    assert last.bindings[0].part_name == "custom/H.xml" and last.bindings[0].origin_section == 0
    assert [s.part_name for s in c.sections.stories] == ["custom/H.xml"]
    assert resolve(ET.fromstring(parts[MAIN]), first.references[0].anchor).tag.endswith(
        "}headerReference"
    )


def test_current_section_history_keeps_source_ownership_without_reading_old_references():
    hist = previous("sectPr", reference("Missing"))
    body = alternate(choice("w", section(history=hist)))
    c = read(fixture(body)[0])
    assert (
        c.status == "ready" and c.sections.sections[0].references == () and c.sections.stories == ()
    )
    h = c.sections.histories[0]
    assert h.anchor.path == (0, 0, 0, 0, 0) and h.owner_anchor.path == (0, 0, 0, 0)
    assert h.previous_anchor.path == (0, 0, 0, 0, 0, 0)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_selected_note_definitions_keep_nested_physical_target_paths(strict, encoding):
    foot = alternate(
        choice("x", note("2", "unsupported")) + choice("w", note("2") + note("3", "separator"))
    )
    raw, parts = fixture(foot=foot, end=note("4", kind="endnote"), strict=strict, encoding=encoding)
    c = read(raw)
    assert c.status == "ready" and c.notes.status == "indexed"
    p = next(p for p in c.notes.parts if p.kind == "footnote")
    assert p.linked and [d.note_id for d in p.definitions] == [2, 3]
    assert [d.anchor.path for d in p.definitions] == [(0, 1, 0), (0, 1, 1)]
    assert p.definitions[1].note_type == "separator"
    assert (
        resolve(ET.fromstring(parts[p.part_name]), p.definitions[0].anchor).get(
            "{" + (S if strict else W) + "}id"
        )
        == "2"
    )


def test_absent_style_and_note_parts_do_not_fabricate_definitions():
    c = read(fixture()[0])
    assert (
        c.status == "ready"
        and c.styles.status == c.table_styles.status == c.notes.status == "absent"
    )
    assert c.styles.styles == c.notes.parts == c.sections.stories == ()
    assert c.sections.sections[0].anchor is None


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(styles=alternate(choice("w", style("A") + style("A")))),
        dict(styles=alternate(choice("w", "<w:unsupported/>"))),
        dict(settings=alternate(choice("w", '<w:evenAndOddHeaders w:val="bad"/>'))),
        dict(foot=alternate(choice("w", note("2") + note("2")))),
        dict(foot=alternate(choice("w", note("2", "unsupported")))),
        dict(body=alternate(choice("w", section(reference("Missing"))))),
    ],
)
def test_invalid_selected_catalog_is_atomic(kwargs):
    blocked(fixture(**kwargs)[0])


def test_ambiguous_part_bindings_still_refuse_after_selection():
    raw, _ = fixture(
        styles=style("A"),
        extras={"custom/Other.xml": part_xml("styles", style("B"))},
        types={"custom/Other.xml": BASE + "styles+xml"},
    )
    blocked(raw)
    blocked(
        fixture(
            foot=note(),
            links=[
                {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
                {"Id": "F2", "Type": R + "footnotes", "Target": "Foot.xml"},
            ],
        )[0]
    )


def test_component_state_does_not_leak_between_consecutive_sources():
    a = fixture(
        styles=alternate(choice("w", style("A", "<w:rPr><w:vanish/></w:rPr>", kind="character")))
    )[0]
    b = fixture(
        styles=alternate(
            choice("w", style("A", '<w:rPr><w:vanish w:val="false"/></w:rPr>', kind="character"))
        )
    )[0]
    x, y, z = read(a), read(b), read(a)
    assert x.styles.styles[0].properties.vanish.value is True
    assert y.styles.styles[0].properties.vanish.value is False and z == x
    assert x.styles.context_sha256 != y.styles.context_sha256
