"""Whole-input compatibility bounds, atomic scope and inert source-only processing."""

import io
import os
import subprocess
import sys
from dataclasses import fields
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_compatibility_catalog import (
    MAIN,
    MC,
    W,
    X,
    actions,
    alternate,
    api,
    blocked,
    choice,
    digest,
    error,
    read,
    source,
)
from test_docx_section_catalog import BASE


def part(content="<w:p/>", attrs='mc:Ignorable="x"', root="hdr"):
    return (
        f'<w:{root} xmlns:w="{W}" xmlns:mc="{MC}" xmlns:x="{X}" {attrs}>' + content + f"</w:{root}>"
    ).encode()


def test_all_declared_candidates_including_unused_are_sorted_and_atomic():
    names = ("styles", "settings", "header", "footer", "footnotes", "endnotes")
    extras = {f"custom/{name}.xml": part() for name in names}
    types = {f"custom/{name}.xml": BASE + name + "+xml" for name in names}
    extras["custom/Comments.xml"] = part(attrs='mc:Unknown="opaque"')
    types["custom/Comments.xml"] = BASE + "comments+xml"
    raw, _ = source("<w:p/>", 'mc:Ignorable="x"', extras=extras, types=types)
    c = read(raw)
    assert c.status == "indexed" and c.issues == ()
    assert [p.part_name for p in c.parts] == sorted(
        [MAIN, *(n for n in extras if "Comments" not in n)]
    )
    assert all(p.root_anchor.path == () and len(p.actions) == 1 for p in c.parts)
    extras["custom/styles.xml"] = part(attrs='mc:Unknown="opaque"')
    c = read(source("<w:p/>", 'mc:Ignorable="x"', extras=extras, types=types)[0])
    assert c.status == "blocked" and c.parts == () and len(c.issues) == 1
    assert c.issues[0].anchor.part_name == "custom/styles.xml"


def test_exact_aggregate_nodes_parts_namespaces_actions_and_manifest():
    extra = part("<x:drop/>")
    raw, xml = source(
        "<x:drop/>",
        'mc:Ignorable="x"',
        extras={"custom/Spare.xml": extra},
        types={"custom/Spare.xml": BASE + "header+xml"},
    )
    nodes = sum(len(list(ET.fromstring(x).iter())) for x in (xml, extra))
    c = read(raw)
    caps = dict(
        max_xml_nodes=nodes,
        max_parts=2,
        max_namespace_declarations=8,
        max_mc_items=4,
        max_actions=4,
        max_manifest_bytes=len(digest(c)),
    )
    assert read(raw, limits=api().CompatibilityLimits(**caps)) == c
    for name, value in caps.items():
        error(
            "compatibility_limit_exceeded",
            lambda name=name, value=value: read(
                raw, limits=api().CompatibilityLimits(**{name: value - 1})
            ),
        )


def test_raw_budgets_cover_discarded_unused_input_before_any_semantic_scan(monkeypatch):
    scanner = import_module("ara.docx_analysis.compatibility._scan")

    def forbidden(*a, **kw):
        raise AssertionError("Semantic scan before aggregate raw preflight")

    monkeypatch.setattr(scanner, "scan_part", forbidden)
    content = alternate(choice("x", '<x:drop mc:Ignorable="x x x x"/>') + choice("w"))
    extra = part(content, attrs='xmlns:huge="' + "x" * 2048 + '"')
    raw, _ = source(
        "<w:p/>",
        'mc:Unknown="bad"',
        extras={"custom/Spare.xml": extra},
        types={"custom/Spare.xml": BASE + "header+xml"},
    )
    for caps in (
        dict(max_parts=1),
        dict(max_namespace_declarations=8),
        dict(max_mc_items=6),
        dict(max_xml_depth=3),
        dict(max_xml_nodes=5),
        dict(max_xml_characters=1024),
    ):
        error(
            "compatibility_limit_exceeded",
            lambda caps=caps: read(raw, limits=api().CompatibilityLimits(**caps)),
        )


def test_xml_characters_include_expanded_names_attributes_text_and_prefix_bindings():
    raw, xml = source('<w:p x:tag="value">words</w:p>', 'mc:Ignorable="x"')
    root = ET.fromstring(xml)
    count = sum(
        len(n.tag)
        + sum(len(k) + len(v) for k, v in n.attrib.items())
        + len(n.text or "")
        + len(n.tail or "")
        for n in root.iter()
    )
    count += sum(
        len(prefix or "") + len(uri)
        for _, (prefix, uri) in ET.iterparse(io.BytesIO(xml), events=("start-ns",))
    )
    assert read(raw, limits=api().CompatibilityLimits(max_xml_characters=count)).status == "indexed"
    error(
        "compatibility_limit_exceeded",
        lambda: read(raw, limits=api().CompatibilityLimits(max_xml_characters=count - 1)),
    )


def test_list_tokens_in_unselected_requires_and_repeated_declarations_are_bounded():
    raw = source(alternate(choice("x x x x") + choice("w")))[0]
    # 3 MC elements and five Requires tokens; Requires is not an MC attribute.
    assert read(raw, limits=api().CompatibilityLimits(max_mc_items=8)).status == "indexed"
    error(
        "compatibility_limit_exceeded",
        lambda: read(raw, limits=api().CompatibilityLimits(max_mc_items=7)),
    )
    body = '<w:p xmlns:x="urn:a"/><w:p xmlns:x="urn:b"/>'
    raw = source(body)[0]
    assert (
        read(raw, limits=api().CompatibilityLimits(max_namespace_declarations=7)).status == "absent"
    )
    error(
        "compatibility_limit_exceeded",
        lambda: read(raw, limits=api().CompatibilityLimits(max_namespace_declarations=6)),
    )


def test_unicode_ncname_and_wildcard_scope_are_not_python_identifier_rules():
    attrs = 'mc:Ignorable="x" mc:ProcessContent="x:имя-1.а x:_é x:a·b"'
    c = read(source("<x:имя-1.а/><x:_é/><x:a·b/>", attrs)[0])
    assert c.status == "indexed" and [a.kind for a in actions(c)][1:] == ["unwrap_element"] * 3
    for token in ("x:", ":name", "x:9bad", "x:a*b", "x:a\u037eb", "x:\u0300bad"):
        blocked(attrs=f'mc:Ignorable="x" mc:ProcessContent="{token}"')


def test_malformed_mc_in_discarded_branch_is_a_conservative_explicit_gate():
    blocked(alternate(choice("x", '<w:p mc:Ignorable="missing"/>') + choice("w")))
    blocked('<x:drop><w:p mc:Unknown="bad"/></x:drop>', 'mc:Ignorable="x"')


def test_comments_pi_and_default_namespace_do_not_shift_actual_element_paths():
    body = "<!-- before --><?test value?>" + alternate(
        choice("x") + '<mc:Choice Requires="w"><w:p/></mc:Choice>'
    )
    c = read(source(body)[0])
    assert actions(c)[0].anchor.path == (0, 0) and actions(c)[0].selected_anchor.path == (0, 0, 1)
    body = f'<AlternateContent xmlns="{MC}">' + choice("w") + "</AlternateContent>"
    assert actions(read(source(body)[0]))[0].selected_anchor.path == (0, 0, 0)


def test_exact_limits_input_and_revalidation():
    for f in fields(api().CompatibilityLimits):
        for value in (True, 0, -1, 1.5, f.default + 1):
            error(
                "invalid_input",
                lambda f=f, value=value: api().CompatibilityLimits(**{f.name: value}),
            )
    caps = api().CompatibilityLimits()
    object.__setattr__(caps, "max_actions", True)
    error("invalid_input", lambda: read(source()[0], limits=caps))
    object.__delattr__(caps, "max_actions")
    error("invalid_input", lambda: read(source()[0], limits=caps))
    error("invalid_input", lambda: read(source()[0], limits={}))
    raw = source()[0]
    for bad in (None, bytearray(raw), "bad"):
        error(
            "invalid_input",
            lambda bad=bad: api().read_compatibility_catalog(
                bad, source_sha256=sha256(raw).hexdigest()
            ),
        )
    error("invalid_input", lambda: api().read_compatibility_catalog(raw, source_sha256="A" * 64))
    error("source_mismatch", lambda: api().read_compatibility_catalog(raw, source_sha256="0" * 64))


def test_archive_size_precedes_hash(monkeypatch):
    from ara.docx_package import DocxError

    def forbidden(*a, **kw):
        raise AssertionError("Hash before archive size")

    monkeypatch.setattr(import_module("ara.docx_analysis.compatibility._read"), "sha256", forbidden)
    with pytest.raises(DocxError) as caught:
        api().read_compatibility_catalog(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


def test_fresh_process_uses_given_bytes_only_and_no_semantic_dom():
    raw = source(alternate(choice("w")))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O or DOM")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
class NoTree(ET.TreeBuilder):
    def __new__(cls,*a,**kw): raise AssertionError("Unexpected DOM allocation")
ET.TreeBuilder=NoTree
ET.fromstring=ET.parse=forbidden
from ara.docx_analysis.compatibility import read_compatibility_catalog
c=read_compatibility_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="indexed" and len(c.parts)==1 and len(c.parts[0].actions)==1
assert not hasattr(c,"complete") and not hasattr(c,"analysis_text")
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


def test_requires_all_uris_and_first_supported_choice_are_used():
    c = read(source(alternate(choice("w x") + choice("w r xml") + choice("w")))[0])
    assert actions(c)[0].selected_anchor.path == (0, 0, 1)
    assert c.status == "indexed"


def test_sibling_ignorable_and_process_content_rules_do_not_leak():
    body = '<w:p mc:Ignorable="x" mc:ProcessContent="x:*"><x:keep/></w:p><x:keep/>'
    c = read(source(body)[0])
    assert [(a.kind, a.anchor.path) for a in actions(c)] == [
        ("strip_attributes", (0, 0)),
        ("unwrap_element", (0, 0, 0)),
    ]
    body = '<x:keep xmlns:z="' + X + '" mc:ProcessContent="z:keep"><z:keep/></x:keep>'
    c = read(source(body, 'mc:Ignorable="x" mc:ProcessContent="x:keep"')[0])
    assert [a.kind for a in actions(c)] == ["strip_attributes", "unwrap_element", "unwrap_element"]


def test_ancestor_rules_survive_nested_redeclaration_and_prefix_rebinding():
    body = (
        '<w:p mc:Ignorable="x" mc:ProcessContent="x:*"><x:keep/></w:p>'
        '<w:p xmlns:x="urn:rebound" xmlns:z="' + X + '"><z:keep/><x:unknown/></w:p>'
        "<x:keep/>"
    )
    c = read(source(body, 'mc:Ignorable="x" mc:ProcessContent="x:*"')[0])
    assert [(a.kind, a.anchor.path) for a in actions(c)] == [
        ("strip_attributes", ()),
        ("strip_attributes", (0, 0)),
        ("unwrap_element", (0, 0, 0)),
        ("unwrap_element", (0, 1, 0)),
        ("unwrap_element", (0, 2)),
    ]


def test_default_namespace_binding_does_not_satisfy_an_undeclared_prefix():
    blocked(alternate(choice("unbound", attrs=f' xmlns="{W}"')))
    c = read(source(alternate(choice("w", attrs=f' xmlns="{X}"')))[0])
    assert c.status == "indexed" and actions(c)[0].selected_anchor.path == (0, 0, 0)


def test_discarded_attributes_do_not_leak_into_reprs_or_catalog_value_fields():
    raw = source('<w:p x:tag="PRIVATE-ATTRIBUTE"/>', 'mc:Ignorable="x"')[0]
    c = read(raw)
    text = digest(c).decode() + repr(c) + repr(c.parts) + repr(actions(c))
    assert "PRIVATE-ATTRIBUTE" not in text and not hasattr(c, "_original")
    assert not hasattr(c, "__dict__") and not hasattr(c.parts[0], "__dict__")
    assert all(not hasattr(a, "__dict__") for a in actions(c))


def test_unwrapped_selected_branch_checks_mu_but_discarded_xml_properties_stay_in_source():
    blocked('<x:keep mc:MustUnderstand="x"/>', 'mc:Ignorable="x" mc:ProcessContent="x:*"')
    body = '<x:drop xml:space="preserve" mc:MustUnderstand="x"/>'
    c = read(source(body, 'mc:Ignorable="x"')[0])
    assert c.status == "indexed" and actions(c)[-1].kind == "ignore_element"
    for attr in ('xml:base="here"', 'xml:lang="ru"'):
        blocked(f"<x:keep {attr}/>", 'mc:Ignorable="x" mc:ProcessContent="x:*"')


def test_every_active_alternative_has_its_own_must_understand_requirement():
    body = alternate(choice("x"), ' mc:MustUnderstand="x"')
    blocked(body)
    c = read(source(alternate(choice("x"), ' mc:MustUnderstand="w"'))[0])
    assert c.status == "indexed" and actions(c)[0].selected_anchor is None
    blocked(alternate(choice("x") + '<mc:Fallback mc:MustUnderstand="x"/>'))


def test_namespace_lists_and_process_pairs_have_exact_xml_ncname_boundaries():
    # Names only occur in the QName-valued attribute, avoiding parser-version differences.
    c = read(source(attrs='mc:Ignorable="x" mc:ProcessContent="x:\U00010000 x:a\u203fb"')[0])
    assert c.status == "indexed"
    for value in ("x:\U000f0000", "x:a\u00a0b", "x:a\u203eb", "*:name", "x:a/b"):
        blocked(attrs=f'mc:Ignorable="x" mc:ProcessContent="{value}"')
