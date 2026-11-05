"""Source-bound compatibility decisions are not a claim of visible-content completeness."""

import json
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_move_catalog import resolve
from test_docx_visible_main import SR, R, S, W
from test_docx_visible_main import source as base_source

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
X = "urn:synthetic:new"
Y = "urn:synthetic:other"
MAIN = "custom/Main.xml"
PROFILE = "docx-compatibility/base-word-selection-v1"


def api():
    return import_module("ara.docx_analysis.compatibility")


def source(body="<w:p/>", attrs="", *, strict=False, encoding="utf-8", extras=None, types=None):
    w, r = (S, SR) if strict else (W, R)
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:document xmlns:w="{w}" xmlns:r="{r[:-1]}" xmlns:mc="{MC}" '
        f'xmlns:x="{X}" xmlns:y="{Y}" {attrs}><w:body>{body}</w:body></w:document>'
    ).encode(encoding)
    raw = base_source(
        "",
        strict=strict,
        encoding=encoding,
        extra_parts={MAIN: xml, **(extras or {})},
        extra_types=types or {},
    )[0]
    return raw, xml


def read(raw, **kw):
    return api().read_compatibility_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kw)


def choice(requires="w", content="<w:p/>", attrs=""):
    return f'<mc:Choice Requires="{requires}"{attrs}>{content}</mc:Choice>'


def alternate(content, attrs=""):
    return f"<mc:AlternateContent{attrs}>{content}</mc:AlternateContent>"


def actions(catalog):
    return [action for part in catalog.parts if part.part_name == MAIN for action in part.actions]


def blocked(body="<w:p/>", attrs=""):
    c = read(source(body, attrs)[0])
    assert c.status == "blocked" and c.parts == () and len(c.issues) == 1
    assert c.issues[0].anchor.part_name == MAIN
    return c


def error(code, call):
    with pytest.raises(api().CompatibilityCatalogError) as caught:
        call()
    assert caught.value.code == code


def digest(catalog):
    value = asdict(catalog)
    value.pop("catalog_sha256")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_first_understood_choice_keeps_physical_original_anchor(strict, encoding):
    body = alternate(
        choice("x")
        + choice("w", "<w:p><w:r><w:t>PRIVATE</w:t></w:r></w:p>")
        + choice("r")
        + "<mc:Fallback><w:p/></mc:Fallback>"
    )
    raw, xml = source(body, strict=strict, encoding=encoding)
    c = read(raw)
    assert c.status == "indexed" and c.profile == PROFILE and c.issues == ()
    assert c.catalog_sha256 == sha256(digest(c)).hexdigest()
    (a,) = actions(c)
    assert a.kind == "alternate_content" and a.anchor.path == (0, 0)
    assert a.selected_anchor.path == (0, 0, 1) and a.attribute_names == ()
    assert resolve(ET.fromstring(xml), a.selected_anchor).tag == "{" + MC + "}Choice"
    assert "PRIVATE" not in repr(c) + digest(c).decode()
    assert not hasattr(c, "complete") and sha256(raw).hexdigest() == c.source_sha256
    with pytest.raises(FrozenInstanceError):
        c.status = "blocked"


@pytest.mark.parametrize("fallback", [False, True])
def test_fallback_or_no_selection_does_not_invent_a_branch(fallback):
    body = alternate(choice("x") + ("<mc:Fallback><w:p/></mc:Fallback>" if fallback else ""))
    c = read(source(body)[0])
    (a,) = actions(c)
    assert c.status == "indexed" and a.kind == "alternate_content"
    assert (a.selected_anchor.path if a.selected_anchor else None) == (
        (0, 0, 1) if fallback else None
    )


def test_prefix_rebinding_is_choice_local_and_restored_for_next_sibling():
    first = alternate(choice("x", attrs=f' xmlns:x="{W}"'))
    second = alternate(choice("x") + "<mc:Fallback/>")
    c = read(source(first + second)[0])
    assert c.status == "indexed"
    assert [a.selected_anchor.path for a in actions(c)] == [(0, 0, 0), (0, 1, 1)]


def test_ignorable_inherits_uris_not_lexical_prefixes_and_keeps_known_attrs():
    body = f'<w:p xmlns:x="{W}" xmlns:z="{X}" x:rsidR="00000001" z:tag="PRIVATE"/>'
    c = read(source(body, 'mc:Ignorable="x"')[0])
    assert c.status == "indexed"
    by_path = {a.anchor.path: a for a in actions(c)}
    assert by_path[()].attribute_names == ("{" + MC + "}Ignorable",)
    assert by_path[(0, 0)].attribute_names == ("{" + X + "}tag",)


def test_unknown_ignorable_element_suppresses_all_descendant_actions_and_mu_requirements():
    nested = alternate(choice("w"))
    body = '<x:drop mc:MustUnderstand="x">' + nested + "</x:drop>"
    c = read(source(body, 'mc:Ignorable="x"')[0])
    assert c.status == "indexed"
    assert [(a.kind, a.anchor.path) for a in actions(c)] == [
        ("strip_attributes", ()),
        ("ignore_element", (0, 0)),
    ]


@pytest.mark.parametrize("pattern", ["x:keep", "x:*"])
def test_process_content_unwraps_only_the_original_matching_element(pattern):
    body = '<x:keep><w:p mc:Ignorable="y" y:tag="PRIVATE"/></x:keep><x:drop/>'
    c = read(source(body, f'mc:Ignorable="x" mc:ProcessContent="{pattern}"')[0])
    assert c.status == "indexed"
    by_path = {a.anchor.path: a.kind for a in actions(c)}
    assert by_path[(0, 0)] == "unwrap_element"
    assert by_path[(0, 0, 0)] == "strip_attributes"
    assert by_path[(0, 1)] == ("unwrap_element" if pattern.endswith("*") else "ignore_element")


def test_nested_alternatives_inside_unselected_choice_do_not_leak_decisions():
    nested = alternate(choice("w"))
    body = alternate(choice("x", nested) + choice("w", nested) + "<mc:Fallback/>")
    c = read(source(body)[0])
    assert [a.anchor.path for a in actions(c)] == [(0, 0), (0, 0, 1, 0)]


def test_known_namespace_is_not_ignored_even_when_declared_ignorable():
    c = read(source('<w:p w:rsidR="00000000"/>', 'mc:Ignorable="w"')[0])
    assert c.status == "indexed"
    assert len(actions(c)) == 1 and actions(c)[0].kind == "strip_attributes"


def test_unknown_non_ignorable_markup_remains_for_downstream_content_proof():
    c = read(source('<x:unknown x:attr="PRIVATE"/>')[0])
    assert c.status == "absent" and c.parts[0].actions == () and c.issues == ()


def test_empty_lists_and_xml_whitespace_are_valid_but_not_new_capabilities():
    c = read(
        source(
            "<w:p/>", 'mc:Ignorable="" mc:ProcessContent="" mc:MustUnderstand="  w&#x9;r&#xA;xml  "'
        )[0]
    )
    assert c.status == "indexed" and len(actions(c)) == 1
    assert len(actions(c)[0].attribute_names) == 3


def test_unknown_mu_only_blocks_active_content():
    inactive = choice("x", '<w:p mc:MustUnderstand="x"/>', ' mc:MustUnderstand="x"')
    c = read(source(alternate(inactive + choice("w")))[0])
    assert c.status == "indexed"
    blocked('<w:p mc:MustUnderstand="x"/>')
    blocked(alternate(choice("w", attrs=' mc:MustUnderstand="x"')))
    blocked(alternate(choice("x"), ' mc:MustUnderstand="x"'))


def test_unknown_ignorable_extension_children_and_attributes_on_alternate_are_accounted():
    body = alternate(
        "<x:future/>" + choice("w", attrs=' x:tag="PRIVATE"'), ' mc:Ignorable="x" x:tag="PRIVATE"'
    )
    c = read(source(body)[0])
    assert c.status == "indexed"
    assert [(a.kind, a.anchor.path) for a in actions(c)] == [
        ("alternate_content", (0, 0)),
        ("ignore_element", (0, 0, 0)),
    ]
    assert actions(c)[0].selected_anchor.path == (0, 0, 1)


@pytest.mark.parametrize(
    "body,attrs",
    [
        ("<w:p/>", 'mc:Ignorable="missing"'),
        ("<w:p/>", 'mc:Ignorable="mc"'),
        ("<w:p/>", 'mc:MustUnderstand="missing"'),
        ("<w:p/>", 'mc:MustUnderstand="mc"'),
        ("<w:p/>", 'mc:Ignorable="x\u00a0y"'),
        ("<w:p/>", 'mc:ProcessContent="x:keep"'),
        ("<w:p/>", 'mc:Ignorable="x" mc:ProcessContent="x:9bad"'),
        ("<w:p/>", 'mc:Ignorable="x" mc:ProcessContent="x:a:b"'),
        ("<w:p/>", 'mc:Ignorable="x" mc:PreserveElements="x:*"'),
        ('<mc:Choice Requires="w"/>', ""),
        ("<mc:Fallback/>", ""),
        ("<mc:Unknown/>", ""),
        (alternate(""), ""),
        (alternate("<mc:Choice/>"), ""),
        (alternate(choice("")), ""),
        (alternate(choice("missing")), ""),
        (alternate(choice("mc")), ""),
        (alternate(choice("w\u00a0r")), ""),
        (alternate(choice() + "<mc:Fallback/><mc:Fallback/>"), ""),
        (alternate(choice() + "<mc:Fallback/>" + choice()), ""),
        (alternate(alternate(choice())), ""),
        (alternate(choice(), ' xml:space="preserve"'), ""),
        (alternate(choice(), ' bad="value"'), ""),
        (alternate(choice(), ' x:tag="value"'), ""),
        (alternate(choice() + '<mc:Fallback Requires="w"/>'), ""),
        (alternate("<w:p/>" + choice(), ' mc:Ignorable="w"'), ""),
        (alternate("<x:keep/>" + choice(), ' mc:Ignorable="x" mc:ProcessContent="x:keep"'), ""),
        ('<x:keep xml:space="preserve"/>', 'mc:Ignorable="x" mc:ProcessContent="x:keep"'),
        (alternate("Unexpected" + choice()), ""),
    ],
)
def test_malformed_or_unsupported_compatibility_is_atomic(body, attrs):
    blocked(body, attrs)
