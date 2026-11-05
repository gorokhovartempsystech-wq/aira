"""Logical XML navigation retains original source identities and character ownership."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from test_docx_compatibility_catalog import MAIN, alternate, choice, source
from test_docx_move_catalog import resolve
from test_docx_table_catalog import paragraph


def api():
    return import_module("ara.docx_analysis.compatibility_view")


def build(raw, **kw):
    return api().build_compatibility_view(raw, source_sha256=sha256(raw).hexdigest(), **kw)


def main(view):
    return next(p for p in view.parts if p.part_name == MAIN)


def assert_blocked(raw, code):
    v = build(raw)
    assert v.status == "blocked" and v.parts == () and len(v.issues) == 1
    assert v.issues[0].code == code
    return v


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_original_addresses_and_order_after_nested_selection_and_promotion(strict, encoding):
    nested = alternate(
        choice("x", paragraph("discarded")) + "<mc:Fallback>" + paragraph("B") + "</mc:Fallback>"
    )
    body = (
        "<x:drop/>"
        + alternate(choice("w", paragraph("A") + nested))
        + "<x:keep>"
        + paragraph("C")
        + "</x:keep>"
    )
    raw, xml = source(
        body, 'mc:Ignorable="x" mc:ProcessContent="x:keep"', strict=strict, encoding=encoding
    )
    v = build(raw)
    assert v.status == "ready" and v.profile == "docx-compatibility/original-logical-view-v1"
    assert v.issues == () and v.catalog.status == "indexed"
    root, original = main(v).root, ET.fromstring(xml)
    p1, p2, p3 = root[0]
    assert [p.anchor.path for p in root[0]] == [(0, 1, 0, 0), (0, 1, 0, 1, 1, 0), (0, 2, 0)]
    assert [p[0][0].text for p in root[0]] == ["A", "B", "C"]
    for node in main(v).nodes.values():
        original_node = resolve(original, node.anchor)
        assert node.tag == original_node.tag and node.text == original_node.text
        assert node.tail == original_node.tail
        assert v.node(node.anchor) is node
    assert p1 is main(v).nodes[p1.anchor.path] and p2 is root[0][1] and p3 is root[0][-1]
    assert len(root[0][:2]) == 2 and list(root[0]) == [p1, p2, p3]
    assert not hasattr(v, "complete") and not hasattr(v, "analysis_text")
    assert sha256(raw).hexdigest() == v.source_sha256


def test_selected_and_dropped_wrappers_are_absent_from_original_lookup():
    raw = source(alternate(choice("x", paragraph("no")) + choice("w", paragraph("yes"))))[0]
    v = build(raw)
    template = main(v).root.anchor
    for path in ((0, 0), (0, 0, 0), (0, 0, 0, 0), (0, 0, 1)):
        assert v.node(replace(template, path=path)) is None
    assert v.node(replace(template, path=(0, 0, 1, 0)))[0][0].text == "yes"


@pytest.mark.parametrize("inner", [choice("x"), choice("w", ""), choice("x") + "<mc:Fallback/>"])
def test_empty_selected_or_missing_branch_creates_no_placeholder(inner):
    raw = source(alternate(inner) + paragraph("after"))[0]
    v = build(raw)
    assert v.status == "ready" and len(main(v).root[0]) == 1
    assert main(v).root[0][0].anchor.path == (0, 1)


def test_no_mc_is_identity_of_original_nodes_attributes_and_text():
    raw, xml = source('<w:p custom="opaque"><x:opaque>PRIVATE</x:opaque></w:p>')
    v = build(raw)
    assert v.status == "ready" and v.catalog.status == "absent"
    original = ET.fromstring(xml)
    for node in main(v).nodes.values():
        actual = resolve(original, node.anchor)
        assert (node.tag, dict(node.attrib), node.text, node.tail) == (
            actual.tag,
            actual.attrib,
            actual.text,
            actual.tail,
        )
    assert main(v).root[0][0].get("custom") == "opaque"
    assert main(v).root[0][0].get("missing", "default") == "default"


def test_only_selected_ignored_attributes_are_removed_and_text_is_not_normalized():
    body = '<w:p x:tag="PRIVATE"><w:r><w:t xml:space="preserve"> A 🧪 \tБ </w:t></w:r></w:p>'
    raw = source(body, 'mc:Ignorable="x"')[0]
    v = build(raw)
    root = main(v).root
    assert root.attrib == {} and root[0][0].attrib == {}
    t = root[0][0][0][0]
    assert (
        t.text == " A 🧪 \tБ "
        and t.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
    )
    with pytest.raises(TypeError):
        t.attrib["x"] = "bad"
    with pytest.raises(TypeError):
        main(v).nodes[()] = t
    with pytest.raises(FrozenInstanceError):
        t.text = "changed"
    with pytest.raises(FrozenInstanceError):
        v.status = "changed"
    assert all(not hasattr(x, "__dict__") for x in (v, main(v), t))
    assert not isinstance(t, ET.Element)
    assert "PRIVATE" not in repr(v) + repr(main(v)) + repr(root[0][0]) + repr(t)


@pytest.mark.parametrize(
    "body",
    [
        "<w:p>text<x:drop/></w:p>",
        "<w:p><x:drop/>tail</w:p>",
        "<x:keep>leading<w:p/></x:keep>",
        "<x:keep><w:p/>trailing</x:keep>",
        alternate(choice("w", "leading<w:p/>")),
        alternate(choice("w", "<w:p/>trailing")),
        "<w:p>\u00a0<x:drop/></w:p>",
    ],
)
def test_mixed_character_ownership_is_explicit_atomic_refusal(body):
    raw = source(body, 'mc:Ignorable="x" mc:ProcessContent="x:keep"')[0]
    assert_blocked(raw, "unsupported_compatibility_text_boundary")


@pytest.mark.parametrize("leaf", ["t", "delText", "instrText", "delInstrText"])
def test_structural_changes_inside_word_text_leaves_are_refused_even_if_whitespace_only(leaf):
    body = f"<w:p><w:r><w:{leaf}><x:drop/> </w:{leaf}></w:r></w:p>"
    assert_blocked(source(body, 'mc:Ignorable="x"')[0], "unsupported_compatibility_text_boundary")


def test_unselected_and_ignored_payload_character_data_does_not_leak_or_block():
    body = "<x:drop>PRIVATE<x:inner/>payload</x:drop>" + alternate(
        choice("x", "PRIVATE") + choice("w", paragraph("visible"))
    )
    v = build(source(body, 'mc:Ignorable="x"')[0])
    assert v.status == "ready" and main(v).root[0][0][0][0].text == "visible"
    assert all("PRIVATE" not in (n.text or "") for n in main(v).nodes.values())
