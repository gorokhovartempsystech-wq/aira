"""Bounded graph/whole-source parsing, immutable proof and no application I/O."""

import os
import subprocess
import sys
from dataclasses import fields
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_table_styles import api, error, fixture, index, payload, read, style, table_style


def test_exact_xml_chain_links_and_manifest_boundaries():
    raw, xml = fixture(table_style("A", '<w:basedOn w:val="B"/>') + table_style("B"))
    nodes = len(list(ET.fromstring(xml).iter()))
    limits = api().TableStyleLimits(
        max_xml_nodes=nodes, max_xml_depth=3, max_styles=2, max_chain_depth=2, max_chain_links=3
    )
    c = read(raw, limits=limits)
    assert index(c)["A"].status == "neutral"
    for values in (
        dict(max_xml_nodes=nodes - 1),
        dict(max_xml_depth=2),
        dict(max_styles=1),
        dict(max_chain_depth=1),
        dict(max_chain_links=2),
    ):
        error(
            "table_style_limit_exceeded",
            lambda values=values: read(raw, limits=api().TableStyleLimits(**values)),
        )
    size = len(payload(c))
    assert read(raw, limits=api().TableStyleLimits(max_manifest_bytes=size)) == c
    error(
        "table_style_limit_exceeded",
        lambda: read(raw, limits=api().TableStyleLimits(max_manifest_bytes=size - 1)),
    )


def test_max_chain_and_many_independent_styles_without_recursion():
    content = "".join(
        table_style(str(i), f'<w:basedOn w:val="{i - 1}"/>' if i else "") for i in range(128)
    )
    c = read(fixture(content)[0])
    assert len(index(c)["127"].chain) == 128
    error(
        "table_style_limit_exceeded",
        lambda: read(fixture(content + table_style("128", '<w:basedOn w:val="127"/>'))[0]),
    )
    c = read(fixture("".join(table_style(str(i)) for i in range(4096)))[0])
    assert len(c.styles) == 4096 and all(len(s.chain) == 1 for s in c.styles)


@pytest.mark.parametrize(
    "what", ["nodes", "depth", "namespace", "text", "attribute", "styles", "regions"]
)
def test_every_opaque_branch_counted_before_any_styles_dom(monkeypatch, what):
    parser = import_module("ara.docx_analysis.visibility._parse")

    def forbidden(*args, **kwargs):
        raise AssertionError("Styles DOM allocated before whole-part preflight")

    monkeypatch.setattr(parser, "Builder", forbidden)
    if what == "nodes":
        content, caps = "<s:payload/>" * 20, dict(max_xml_nodes=10)
    elif what == "depth":
        content, caps = "<s:payload>" * 10 + "</s:payload>" * 10, dict(max_xml_depth=5)
    elif what == "namespace":
        content = '<s:payload xmlns:large="' + "x" * 4096 + '"/>'
        caps = dict(max_xml_characters=1024)
    elif what == "text":
        content, caps = "<s:payload>" + "x" * 4096 + "</s:payload>", dict(max_xml_characters=1024)
    elif what == "attribute":
        content, caps = '<s:payload s:v="' + "x" * 4096 + '"/>', dict(max_xml_characters=1024)
    elif what == "styles":
        content, caps = "<s:payload>" + table_style("Nested") + "</s:payload>", dict(max_styles=1)
    else:
        content = '<s:payload><w:tblStylePr w:type="firstRow"/>' * 2 + "</s:payload>" * 2
        caps = dict(max_regions=1)
    raw = fixture(table_style(content=content))[0]
    error("table_style_limit_exceeded", lambda: read(raw, limits=api().TableStyleLimits(**caps)))


def test_issue_budget_and_context_read_once(monkeypatch):
    module = import_module("ara.docx_analysis.visibility")
    original, calls = module.read_style_context, []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "read_style_context", counted)
    raw = fixture(table_style(content="<w:unknown/>"))[0]
    c = read(raw, limits=api().TableStyleLimits(max_issues=2))
    assert c.styles[0].status == "blocked" and len(calls) == 1
    error(
        "table_style_limit_exceeded", lambda: read(raw, limits=api().TableStyleLimits(max_issues=1))
    )


def test_strict_inputs_limits_and_source_identity():
    raw = fixture(table_style())[0]
    for bad in (None, bytearray(raw), memoryview(raw), "docx"):
        error(
            "invalid_input",
            lambda bad=bad: api().read_table_style_catalog(
                bad, source_sha256=sha256(raw).hexdigest()
            ),
        )
    for bad in (None, "A" * 64, "a" * 63):
        error(
            "invalid_input", lambda bad=bad: api().read_table_style_catalog(raw, source_sha256=bad)
        )
    error("source_mismatch", lambda: api().read_table_style_catalog(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: read(raw, limits={}))
    for f in fields(api().TableStyleLimits):
        for bad in (True, 0, -1, 1.2, f.default + 1):
            error("invalid_input", lambda f=f, bad=bad: api().TableStyleLimits(**{f.name: bad}))
    for missing in (False, True):
        limit = api().TableStyleLimits()
        if missing:
            object.__delattr__(limit, "max_styles")
        else:
            object.__setattr__(limit, "max_styles", True)
        error("invalid_input", lambda: read(raw, limits=limit))

    class Subclass(api().TableStyleLimits):
        pass

    error("invalid_input", lambda: read(raw, limits=Subclass()))


def test_package_failures_and_oversize_before_hash(monkeypatch):
    from ara.docx_package import DocxError

    for data in (b"not ZIP", b"x" * 33554433):
        with pytest.raises(DocxError):
            read(data)
    module = import_module("ara.docx_analysis.table_styles._read")

    def forbidden(*args, **kwargs):
        raise AssertionError("Hash ran before archive size check")

    monkeypatch.setattr(module, "sha256", forbidden)
    with pytest.raises(DocxError) as caught:
        api().read_table_style_catalog(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


def test_metadata_and_reprs_do_not_expose_author_values_or_source_nodes():
    private = "SYNTHETIC_PRIVATE_TABLE_STYLE"
    raw = fixture(
        table_style(
            private,
            '<w:name w:val="SYNTHETIC_PRIVATE_AUTHOR"/>'
            '<w:aliases w:val="SYNTHETIC_PRIVATE_ALIAS"/>',
        )
    )[0]
    c = read(raw)
    assert private not in repr(c) + repr(c.styles[0])
    encoded = payload(c)
    assert b"SYNTHETIC_PRIVATE_AUTHOR" not in encoded and b"SYNTHETIC_PRIVATE_ALIAS" not in encoded
    assert c.styles[0].style_id == private and isinstance(c.styles[0].metadata, tuple)
    assert not any(isinstance(getattr(c, f.name), (bytes, ET.Element)) for f in fields(c))


def test_fresh_process_factory_and_import_do_not_access_application_io():
    raw = fixture(table_style(content="<w:rPr><w:b/></w:rPr>") + style("P"))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.table_styles import read_table_style_catalog
c=read_table_style_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="ready" and len(c.styles)==1 and c.styles[0].status=="neutral"
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""


def test_global_failure_counts_both_context_and_new_proof_issues():
    raw = fixture(table_style() + table_style())[0]
    c = read(raw, limits=api().TableStyleLimits(max_issues=2))
    assert c.status == "blocked" and len(c.issues) == 1
    error(
        "table_style_limit_exceeded", lambda: read(raw, limits=api().TableStyleLimits(max_issues=1))
    )


@pytest.mark.parametrize(
    "content",
    [
        '<w:rPr><z:b xmlns:z="http://purl.oclc.org/ooxml/wordprocessingml/main"/></w:rPr>',
        '<w:tblStylePr w:type="firstRow"><w:tcPr><w:shd/>PAYLOAD</w:tcPr></w:tblStylePr>',
        '<w:tblStylePr w:type="firstRow"><w:tcPr w:unexpected="x"/></w:tblStylePr>',
    ],
)
def test_mixed_namespaces_and_conditional_tails_never_prove_neutral(content):
    c = read(fixture(table_style(content=content))[0])
    assert c.styles[0].status == "blocked" and c.styles[0].metadata == ()


def test_neutral_proof_does_not_erase_document_default_visibility():
    defaults = (
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>"
    )
    raw = fixture(defaults + table_style())[0]
    c = read(raw)
    context = import_module("ara.docx_analysis.visibility").read_style_context(
        raw, source_sha256=sha256(raw).hexdigest()
    )
    assert c.styles[0].status == "neutral"
    assert context.defaults.vanish.value is True
    assert c.style_context_sha256 == context.context_sha256
