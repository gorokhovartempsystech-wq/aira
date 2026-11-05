"""Whole-source authority, original node lookup and atomic projection boundaries."""

import os
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_compatibility_catalog import MAIN, MC, W, X, alternate, choice, error, source
from test_docx_compatibility_catalog import api as catalog_api
from test_docx_compatibility_view import api, assert_blocked, build, main
from test_docx_section_catalog import BASE


def extra(content="", attrs="", root="hdr"):
    return (
        f'<w:{root} xmlns:w="{W}" xmlns:mc="{MC}" xmlns:x="{X}" {attrs}>{content}</w:{root}>'
    ).encode()


def fixture(content, attrs="", root="hdr"):
    return source(
        "<w:p/>",
        extras={"custom/Z.xml": extra(content, attrs, root)},
        types={"custom/Z.xml": BASE + "header+xml"},
    )[0]


def test_all_scoped_parts_share_one_source_catalog_and_keep_actual_anchors():
    kinds = ("styles", "settings", "header", "footer", "footnotes", "endnotes")
    parts = {
        f"custom/{name}.xml": extra(alternate(choice("w", "<w:p/>")), root=name) for name in kinds
    }
    types = {f"custom/{name}.xml": BASE + name + "+xml" for name in kinds}
    raw, _ = source("<w:p/>", extras=parts, types=types)
    v = build(raw)
    assert v.status == "ready" and [p.part_name for p in v.parts] == sorted([MAIN, *parts])
    for p in v.parts:
        assert (
            p.root.anchor.part_name == p.part_name
            and p.root.anchor.source_sha256 == v.source_sha256
        )
        if p.part_name != MAIN:
            assert p.root[0].anchor.path == (0, 0, 0) and p.root[0].tag == "{" + W + "}p"
            assert v.node(p.root[0].anchor) is p.root[0]


def test_projection_refusal_in_last_part_never_exposes_earlier_ready_parts():
    v = assert_blocked(
        fixture("<x:keep>unsafe<w:p/></x:keep>", 'mc:Ignorable="x" mc:ProcessContent="x:keep"'),
        "unsupported_compatibility_text_boundary",
    )
    assert v.catalog.status == "indexed" and len(v.catalog.parts) == 2
    assert v.issues[0].anchor.part_name == "custom/Z.xml"


def test_ignored_or_unwrapped_part_root_is_not_fabricated_as_a_word_root():
    for attrs in ('mc:Ignorable="x"', 'mc:Ignorable="x" mc:ProcessContent="x:*"'):
        xml = f'<x:root xmlns:x="{X}" xmlns:mc="{MC}" {attrs}/>'.encode()
        raw = source(extras={"custom/Z.xml": xml}, types={"custom/Z.xml": BASE + "header+xml"})[0]
        v = assert_blocked(raw, "unsupported_compatibility_root")
        assert v.issues[0].anchor.path == () and v.issues[0].anchor.part_name == "custom/Z.xml"


def test_all_raw_bounds_and_mc_syntax_precede_any_semantic_tree(monkeypatch):
    module = import_module("ara.docx_analysis.compatibility_view._project")

    def forbidden(*a, **kw):
        raise AssertionError("Semantic tree before whole-input validation")

    monkeypatch.setattr(module, "build_tree", forbidden)
    raw = fixture(
        alternate(choice("x", '<x:drop mc:Ignorable="x x x x"/>') + choice("w")),
        'xmlns:huge="' + "a" * 2048 + '"',
    )
    for caps in (
        dict(max_parts=1),
        dict(max_xml_nodes=5),
        dict(max_xml_depth=3),
        dict(max_xml_characters=1024),
        dict(max_mc_items=3),
        dict(max_namespace_declarations=8),
        dict(max_manifest_bytes=1),
    ):
        error(
            "compatibility_limit_exceeded",
            lambda caps=caps: build(raw, limits=catalog_api().CompatibilityLimits(**caps)),
        )
    v = build(fixture('<w:p mc:Unknown="unsupported"/>'))
    assert v.status == "blocked" and v.parts == () and v.issues == v.catalog.issues


def test_only_one_tree_allocation_per_scoped_part_and_no_serialization(monkeypatch):
    module = import_module("ara.docx_analysis.compatibility_view._project")
    original, calls = module.build_tree, []

    def counted(*a, **kw):
        calls.append(a[1])
        return original(*a, **kw)

    def forbidden(*a, **kw):
        raise AssertionError("Serializing a filtered source is forbidden")

    raw = fixture(alternate(choice("w", "<w:p/>")))
    monkeypatch.setattr(module, "build_tree", counted)
    monkeypatch.setattr(ET, "tostring", forbidden)
    v = build(raw)
    for _ in range(5):
        for p in v.parts:
            for node in p.nodes.values():
                assert v.node(node.anchor) is node
    assert calls == [MAIN, "custom/Z.xml"]
    assert sha256(raw).hexdigest() == v.source_sha256


def test_original_anchor_lookup_rejects_wrong_source_or_malformed_values():
    v = build(source()[0])
    anchor = main(v).root.anchor
    error("source_mismatch", lambda: v.node(replace(anchor, source_sha256="0" * 64)))
    for bad in (
        None,
        {},
        replace(anchor, path=[0]),
        replace(anchor, path=(True,)),
        replace(anchor, path=(-1,)),
        replace(anchor, path=(0,) * 129),
        replace(anchor, part_name=""),
        replace(anchor, source_sha256="bad"),
    ):
        error("invalid_input", lambda bad=bad: v.node(bad))
    assert v.node(replace(anchor, path=(999,))) is None
    assert v.node(replace(anchor, part_name="custom/Missing.xml")) is None


def test_view_factory_revalidates_source_and_limits_without_accepting_prepared_catalog():
    raw = source()[0]
    for bad in (None, "bad", bytearray(raw)):
        error(
            "invalid_input",
            lambda bad=bad: api().build_compatibility_view(
                bad, source_sha256=sha256(raw).hexdigest()
            ),
        )
    error("source_mismatch", lambda: api().build_compatibility_view(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: build(raw, limits={}))
    caps = catalog_api().CompatibilityLimits()
    object.__setattr__(caps, "max_actions", True)
    error("invalid_input", lambda: build(raw, limits=caps))
    with pytest.raises(TypeError):
        build(raw, catalog={})


def test_deep_promotions_retain_unique_nodes_without_cross_product_expansion():
    payload = "<w:p><w:r><w:t>text</w:t></w:r></w:p>" * 40
    nested = "<x:keep>" * 40 + payload + "</x:keep>" * 40
    v = build(source(nested, 'mc:Ignorable="x" mc:ProcessContent="x:keep"')[0])
    p = main(v)
    assert v.status == "ready" and len(p.root[0]) == 40 and len(p.nodes) == 122
    assert len({id(n) for n in p.nodes.values()}) == 122
    assert p.root[0][0].anchor.path == (0,) + (0,) * 40 + (0,)
    assert p.root[0][-1].anchor.path == (0,) + (0,) * 40 + (39,)


def test_fresh_process_uses_original_bytes_without_application_io():
    raw = source(alternate(choice("w", "<w:p/>")))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected I/O or serialization")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.compatibility_view import build_compatibility_view
v=build_compatibility_view(data,source_sha256=sha256(data).hexdigest())
assert v.status=="ready" and v.parts[0].root[0][0].anchor.path==(0,0,0,0)
assert not hasattr(v,"complete") and not hasattr(v,"analysis_text")
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        timeout=30,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_original_parsed_elements_are_never_mutated_or_reparented(monkeypatch):
    module = import_module("ara.docx_analysis.compatibility_view._project")
    original, roots = module.build_tree, []

    def capture(*args):
        root = original(*args)
        roots.append(root)
        return root

    monkeypatch.setattr(module, "build_tree", capture)
    body = '<x:keep><w:p x:tag="PRIVATE"/></x:keep><x:drop/>'
    v = build(source(body, 'mc:Ignorable="x" mc:ProcessContent="x:keep"')[0])
    assert v.status == "ready" and len(main(v).root[0]) == 1
    assert len(roots) == 1 and roots[0].get("{" + MC + "}Ignorable") == "x"
    assert roots[0][0][0].tag == "{" + X + "}keep" and len(roots[0][0]) == 2
    assert roots[0][0][0][0].get("{" + X + "}tag") == "PRIVATE"
    assert main(v).root[0][0].attrib == {}


def test_structural_root_alternative_is_refused_without_promoting_an_invented_root():
    xml = (
        f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:w="{W}">'
        + choice("w", "<w:hdr/>")
        + "</mc:AlternateContent>"
    ).encode()
    raw = source(extras={"custom/Z.xml": xml}, types={"custom/Z.xml": BASE + "header+xml"})[0]
    v = assert_blocked(raw, "unsupported_compatibility_root")
    assert v.issues[0].anchor.part_name == "custom/Z.xml"


def test_text_leaf_attribute_removal_keeps_original_literal_source_whitespace():
    body = '<w:p><w:r><w:t x:tag="PRIVATE" xml:space="preserve">  A\tБ  </w:t>\n</w:r></w:p>'
    v = build(source(body, 'mc:Ignorable="x"')[0])
    node = main(v).root[0][0][0][0]
    assert v.status == "ready" and node.text == "  A\tБ  " and node.tail == "\n"
    assert dict(node.attrib) == {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}


def test_non_xml_whitespace_after_removed_element_is_not_silently_lost():
    v = assert_blocked(
        source("<x:drop/>\u00a0", 'mc:Ignorable="x"')[0], "unsupported_compatibility_text_boundary"
    )
    assert v.issues[0].anchor.path == (0,)


def test_maximum_xml_depth_retains_original_text_path_without_recursion_failure():
    content = "<x:keep>" * 123 + "<w:p><w:r><w:t>T</w:t></w:r></w:p>" + "</x:keep>" * 123
    raw = source(content, 'mc:Ignorable="x" mc:ProcessContent="x:keep"')[0]
    v = build(raw)
    assert v.status == "ready" and len(main(v).root[0][0][0][0].anchor.path) == 127
    error(
        "compatibility_limit_exceeded",
        lambda: build(raw, limits=catalog_api().CompatibilityLimits(max_xml_depth=127)),
    )


def test_removed_ignorable_extension_child_does_not_become_an_extra_selected_child():
    body = alternate(
        "<x:extension>PRIVATE</x:extension>" + choice("w", "<w:p/>"), ' mc:Ignorable="x"'
    )
    v = build(source(body)[0])
    assert v.status == "ready" and len(main(v).root[0]) == 1
    assert main(v).root[0][0].anchor.path == (0, 0, 1, 0)
    assert all(node.tag != "{" + X + "}extension" for node in main(v).nodes.values())
