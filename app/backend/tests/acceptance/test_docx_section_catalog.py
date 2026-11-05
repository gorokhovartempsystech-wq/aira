"""Ordinary current section definitions and original reference provenance."""

import json
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_visible_main import SR, R, S, W, source

BASE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
PROFILE = "docx-sections/current-header-footer-definitions-v1"


def api():
    return import_module("ara.docx_analysis.sections")


def reference(key="H", kind="header", variant="default"):
    return f'<w:{kind}Reference r:id="{key}" w:type="{variant}"/>'


def section(refs="", props="", history=""):
    return "<w:sectPr>" + refs + props + history + "</w:sectPr>"


def boundary(props):
    return "<w:p><w:pPr>" + props + "</w:pPr><w:r><w:t>End</w:t></w:r></w:p>"


def previous(kind="sectPr", payload=""):
    return (
        f'<w:{kind}Change w:id="7" w:author="PRIVATE">'
        + f"<w:{kind}>"
        + payload
        + f"</w:{kind}></w:{kind}Change>"
    )


def fixture(body=None, *, strict=False, encoding="utf-8", settings=None, links=None, types=None):
    ns, rel = (S, SR) if strict else (W, R)
    parts = {}
    content_types = {}
    relationships = []
    for key, kind in (
        ("H", "header"),
        ("F", "footer"),
        ("First", "header"),
        ("Even", "header"),
        ("Orphan", "header"),
    ):
        path = "custom/" + key + ".xml"
        tag = "hdr" if kind == "header" else "ftr"
        parts[path] = (
            f'<?xml version="1.0" encoding="{encoding}"?><w:{tag} xmlns:w="{ns}">'
            f"<w:p><w:r><w:t>TEXT-{key}</w:t></w:r></w:p></w:{tag}>"
        ).encode(encoding)
        content_types[path] = BASE + kind + "+xml"
        if key != "Orphan":
            relationships.append({"Id": key, "Type": rel + kind, "Target": key + ".xml"})
    if settings is not None:
        parts["custom/Settings.xml"] = (
            f'<?xml version="1.0" encoding="{encoding}"?>'
            f'<w:settings xmlns:w="{ns}">{settings}</w:settings>'
        ).encode(encoding)
        content_types["custom/Settings.xml"] = BASE + "settings+xml"
        relationships.append({"Id": "settings", "Type": rel + "settings", "Target": "Settings.xml"})
    content_types.update(types or {})
    if links is not None:
        relationships = links
    return source(
        body if body is not None else section(reference()),
        strict=strict,
        encoding=encoding,
        extra_parts=parts,
        extra_types=content_types,
        links=relationships,
    )


def read(raw, **kw):
    return api().read_section_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kw)


def payload(c):
    d = asdict(c)
    d.pop("catalog_sha256")
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def error(code, call):
    with pytest.raises(api().SectionCatalogError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_sections_original_provenance_inheritance_and_unique_story_order(strict, encoding):
    refs = (
        reference()
        + reference("F", "footer")
        + reference("First", variant="first")
        + reference("Even", variant="even")
    )
    body = (
        boundary(section(refs))
        + boundary(section(props="<w:titlePg/>"))
        + section(reference("First"))
    )
    raw, xml = fixture(body, settings="<w:evenAndOddHeaders/>", strict=strict, encoding=encoding)
    c = read(raw)
    assert c.profile == PROFILE and c.status == "indexed" and c.issues == ()
    assert c.even_and_odd is True and c.settings_part == "custom/Settings.xml"
    assert len(c.sections) == 3
    assert [s.anchor.path for s in c.sections] == [(0, 0, 0, 0), (0, 1, 0, 0), (0, 2)]
    assert [s.paragraph_anchor.path if s.paragraph_anchor else None for s in c.sections] == [
        (0, 0),
        (0, 1),
        None,
    ]
    assert [s.index for s in c.sections] == [0, 1, 2]
    first, second, third = c.sections
    assert len(first.references) == 4 and second.references == ()
    assert [b.variant for b in second.bindings] == [
        "default",
        "first",
        "even",
        "default",
        "first",
        "even",
    ]
    assert [b.part_name for b in second.bindings] == [
        "custom/H.xml",
        "custom/First.xml",
        "custom/Even.xml",
        "custom/F.xml",
        None,
        None,
    ]
    assert (
        second.bindings[1].origin_section == 0
        and second.bindings[1].definition_anchor == first.references[2].anchor
    )
    assert (
        second.bindings[4].origin_section is None and second.bindings[4].definition_anchor is None
    )
    assert (
        third.bindings[0].part_name == "custom/First.xml" and third.bindings[0].origin_section == 2
    )
    assert [s.part_name for s in c.stories] == [
        "custom/Even.xml",
        "custom/F.xml",
        "custom/First.xml",
        "custom/H.xml",
    ]
    assert all(
        s.root_anchor.path == ()
        and s.root_anchor.part_name == s.part_name
        and s.root_anchor.source_sha256 == c.source_sha256
        for s in c.stories
    )
    root = ET.fromstring(xml)
    for s in c.sections:
        for r in s.references:
            assert resolve(root, r.anchor).tag.endswith("}" + r.kind + "Reference")
    assert read(raw) == c and c.catalog_sha256 == sha256(payload(c)).hexdigest()
    assert not hasattr(c, "analysis_text") and not hasattr(c, "complete")
    assert sha256(raw).hexdigest() == c.source_sha256
    with pytest.raises(FrozenInstanceError):
        second.first_page = False
    assert not hasattr(second, "__dict__")


@pytest.mark.parametrize(
    "flag,enabled",
    [
        ("", False),
        ("<w:titlePg/>", True),
        ('<w:titlePg w:val="0"/>', False),
        ('<w:titlePg w:val="on"/>', True),
    ],
)
def test_first_page_flag_and_inactive_definition_do_not_fall_back(flag, enabled):
    raw, _ = fixture(section(reference() + reference("First", variant="first"), flag))
    c = read(raw)
    assert c.status == "indexed" and c.even_and_odd is False
    assert len(c.sections[0].bindings) == (4 if enabled else 2)
    assert {s.part_name for s in c.stories} == (
        {"custom/H.xml", "custom/First.xml"} if enabled else {"custom/H.xml"}
    )
    assert "custom/Orphan.xml" not in {s.part_name for s in c.stories}


@pytest.mark.parametrize(
    "flag,enabled",
    [
        ("", False),
        ("<w:evenAndOddHeaders/>", True),
        ('<w:evenAndOddHeaders w:val="false"/>', False),
        ('<w:evenAndOddHeaders w:val="1"/>', True),
    ],
)
def test_even_flag_is_global_and_default_inherits_default_not_even(flag, enabled):
    body = boundary(section(reference() + reference("Even", variant="even"))) + section()
    c = read(fixture(body, settings=flag)[0])
    assert c.status == "indexed" and c.even_and_odd is enabled
    assert c.sections[1].bindings[0].part_name == "custom/H.xml"
    assert len(c.sections[1].bindings) == (4 if enabled else 2)
    if enabled:
        assert c.sections[1].bindings[1].part_name == "custom/Even.xml"


def test_implicit_final_section_and_shared_story_are_not_fabricated_xml():
    c = read(
        fixture(boundary(section(reference() + reference(variant="first"), "<w:titlePg/>")))[0]
    )
    assert (
        len(c.sections) == 2
        and c.sections[1].anchor is None
        and c.sections[1].paragraph_anchor is None
    )
    assert c.sections[1].first_page is False and len(c.stories) == 1
    assert c.sections[1].bindings[0].origin_section == 0
    empty = read(source("<w:p/>")[0])
    assert empty.status == "indexed" and len(empty.sections) == 1 and empty.stories == ()
    assert all(b.part_name is None for b in empty.sections[0].bindings)


def test_historical_section_and_paragraph_properties_do_not_activate_old_references():
    old = previous(payload=reference("MISSING") + "<w:titlePg/>")
    p = boundary(section(reference(), history=old) + previous("pPr", section(reference("MISSING"))))
    raw, _ = fixture(p + section())
    c = read(raw)
    assert c.status == "indexed" and len(c.sections) == 2 and len(c.histories) == 2
    assert [h.kind for h in c.histories] == ["section", "paragraph"]
    assert [h.anchor.path for h in c.histories] == [(0, 0, 0, 0, 1), (0, 0, 0, 1)]
    assert all(h.previous_anchor.path == h.anchor.path + (0,) for h in c.histories)
    assert [s.part_name for s in c.stories] == ["custom/H.xml"]
    assert "PRIVATE" not in repr(c) + repr(c.histories)


@pytest.mark.parametrize(
    "bad",
    [
        section(reference() + reference()),
        section(props="<w:titlePg/><w:titlePg/>"),
        section('<w:headerReference r:id="H"/>'),
        section('<w:headerReference r:id="H" w:type="odd"/>'),
        section('<w:headerReference r:id="H" w:type="default">TEXT</w:headerReference>'),
        section(props='<w:titlePg w:val="yes"/>'),
        section(props='<w:titlePg w:extra="1"/>'),
        section(props="<w:unknown/>"),
        section(props="<w:titlePg/>" + reference()),
        section() + "<w:p/>",
        section() + section(),
        "<w:p><w:r>" + section(reference()) + "</w:r></w:p>",
        "<s:wrapper>" + section(reference()) + "</s:wrapper>",
        section(props="<w:cols>" + reference() + "</w:cols>"),
        boundary('<w:rPr><w:del w:id="1"/></w:rPr>' + section(reference())),
        boundary(section(history=previous().replace('w:id="7"', 'w:id="bad"'))),
        section(history=previous() + previous()),
    ],
)
def test_bad_current_context_and_reference_markup_cannot_publish_a_good_prefix(bad):
    raw, _ = fixture(boundary(section(reference())) + bad)
    c = read(raw)
    assert c.status == "blocked" and c.sections == c.stories == c.histories == ()
    assert c.even_and_odd is None and len(c.issues) == 1


@pytest.mark.parametrize(
    "link",
    [
        None,
        {"Id": "H", "Type": R + "footer", "Target": "H.xml"},
        {
            "Id": "H",
            "Type": R + "header",
            "Target": "https://invalid.example/header",
            "TargetMode": "External",
        },
    ],
)
def test_reference_requires_matching_internal_main_relationship(link):
    c = read(fixture(links=[] if link is None else [link])[0])
    assert c.status == "blocked" and c.issues[0].code == "unresolved_section_reference"


def test_wrong_story_content_type_blocks_and_no_story_content_is_copied():
    c = read(fixture(types={"custom/H.xml": BASE + "footer+xml"})[0])
    assert c.status == "blocked" and c.issues[0].code == "unresolved_section_reference"
    good = read(fixture()[0])
    assert "TEXT-H" not in repr(good) + repr(good.sections) + repr(good.stories)


@pytest.mark.parametrize(
    "settings",
    [
        "<w:evenAndOddHeaders/><w:evenAndOddHeaders/>",
        '<w:evenAndOddHeaders w:val="bad"/>',
        "<w:compat><w:evenAndOddHeaders/></w:compat>",
    ],
)
def test_settings_flag_is_unique_direct_and_well_formed(settings):
    c = read(fixture(settings=settings)[0])
    assert c.status == "blocked" and c.issues[0].code == "unresolved_section_settings"


def test_orphan_settings_part_is_not_a_silent_default():
    c = read(
        fixture(
            settings="<w:evenAndOddHeaders/>",
            links=[{"Id": "H", "Type": R + "header", "Target": "H.xml"}],
        )[0]
    )
    assert c.status == "blocked" and c.issues[0].code == "unresolved_section_settings"
