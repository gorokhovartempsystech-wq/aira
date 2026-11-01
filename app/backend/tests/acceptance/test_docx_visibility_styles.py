"""Frozen styles-context acceptance: literals and XML anchors independent of reader."""

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict, fields
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from docx_projection_fixtures import package

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://purl.oclc.org/ooxml/wordprocessingml/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
SR = "http://purl.oclc.org/ooxml/officeDocument/relationships/"
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
PRIVATE = "SYNTHETIC_PRIVATE_STYLE"


def api():
    return import_module("ara.docx_analysis.visibility")


def style(identity="A", content="", kind="paragraph", attrs=""):
    return f'<w:style w:type="{kind}" w:styleId="{identity}" {attrs}>{content}</w:style>'


def fixture(content="", *, strict=False, encoding="utf-8", root_attrs="", **kwargs):
    name = "custom/Visibility.xml"
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:styles xmlns:w="{S if strict else W}" xmlns:s="urn:synthetic" '
        f'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" {root_attrs}>'
        + content
        + "</w:styles>"
    ).encode(encoding)
    links = [{"Id": "styles", "Type": (SR if strict else R) + "styles", "Target": "Visibility.xml"}]
    raw = package(
        "<w:p/>",
        main_part="custom/Main.xml",
        strict=strict,
        encoding=encoding,
        extra_parts={name: xml},
        extra_types={name: MIME},
        links=links,
        **kwargs,
    )[0]
    return raw, xml


def read(raw, **kwargs):
    return api().read_style_context(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def by_id(result):
    return {s.style_id: s for s in result.styles}


def assert_digest(result):
    payload = asdict(result)
    payload.pop("context_sha256")
    expected = sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    assert result.context_sha256 == expected


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_nearest_current_values_provenance_and_defaults(strict, encoding):
    content = (
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>"
    )
    content += "<!--not an element--><?pi ignored?>"
    content += style(
        "Z", '<w:rPr><w:vanish/><w:specVanish w:val="off"/></w:rPr>', attrs='w:default="1"'
    )
    content += style(
        "A", '<w:basedOn w:val="Z"/><w:rPr><w:vanish w:val="false"/><w:webHidden/></w:rPr>'
    )
    content += style("B", '<w:basedOn w:val="A"/>')
    content += style("C", "<w:rPr><w:vanish/></w:rPr>", kind="character", attrs='w:default="true"')
    content += style("D", '<w:basedOn w:val="Z"/><w:rPr><w:vanish/></w:rPr>')
    raw, xml = fixture(content, strict=strict, encoding=encoding)
    before = sha256(raw).hexdigest()
    result = read(raw)
    assert result.status == "ready" and result.profile == "docx-visibility/styles-context-v1"
    assert result.styles_part == "custom/Visibility.xml" and result.issues == ()
    assert result.default_paragraph_style == "Z" and result.default_character_style == "C"
    assert [s.style_id for s in result.styles] == ["A", "B", "C", "D", "Z"]
    records = by_id(result)
    assert records["B"].properties.vanish.value is False
    assert records["B"].properties.spec_vanish.value is False
    assert records["B"].properties.web_hidden.value is True
    assert records["D"].properties.vanish.value is True  # no XOR along basedOn
    assert records["C"].properties.spec_vanish.value is None
    assert records["C"].properties.spec_vanish.anchor is None
    assert result.defaults.vanish.value is True
    expected = {"vanish": (2, 1, 0), "spec_vanish": (1, 0, 1), "web_hidden": (2, 1, 1)}
    root = ET.fromstring(xml)
    for name, path in expected.items():
        value = getattr(records["B"].properties, name)
        assert value.anchor.path == path
        assert value.anchor.source_sha256 == before
        assert value.anchor.part_name == result.styles_part
        node = root
        for index in path:
            node = node[index]
        assert (
            node.tag.rsplit("}", 1)[1]
            == {"vanish": "vanish", "spec_vanish": "specVanish", "web_hidden": "webHidden"}[name]
        )
    assert records["A"].anchor.path == (2,) and records["A"].based_on == "Z"
    assert read(raw) == result and sha256(raw).hexdigest() == before
    assert_digest(result)


def test_absent_catalog_and_doc_defaults_are_not_style_values():
    absent = read(package("<w:p/>")[0])
    assert absent.status == "absent" and absent.styles_part is None
    assert absent.styles == absent.issues == ()
    assert absent.defaults.vanish.value is None
    assert absent.default_paragraph_style is absent.default_character_style is None
    raw, _ = fixture(
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/>"
        "</w:rPr></w:rPrDefault></w:docDefaults>" + style()
    )
    result = read(raw)
    assert result.defaults.vanish.value is True
    assert by_id(result)["A"].properties.vanish.value is None
    assert not hasattr(result, "complete") and not hasattr(result, "analysis_text")
    assert_digest(absent)


@pytest.mark.parametrize(
    "token,expected",
    [
        (None, True),
        ("1", True),
        ("true", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("off", False),
    ],
)
def test_boolean_lexemes_and_independent_properties(token, expected):
    attr = "" if token is None else f' w:val="{token}"'
    result = read(
        fixture(
            style(
                content=f"<w:rPr><w:vanish{attr}/><w:specVanish{attr}/><w:webHidden{attr}/></w:rPr>"
            )
        )[0]
    )
    prop = by_id(result)["A"].properties
    assert (prop.vanish.value, prop.spec_vanish.value, prop.web_hidden.value) == (expected,) * 3


def test_ui_metadata_and_histories_never_supply_current_hidden_values():
    content = '<w:latentStyles w:defSemiHidden="1"><w:lsdException w:name="latent" '
    content += 'w:semiHidden="true"/></w:latentStyles>'
    content += style(
        PRIVATE,
        '<w:hidden/><w:semiHidden/><w:name w:val="PRIVATE AUTHOR"/>'
        '<w:link w:val="missing"/><w:next w:val="missing"/>'
        '<w:rPr><w:rPrChange w:id="1" w:author="PRIVATE AUTHOR"><w:rPr>'
        "<w:vanish/><s:payload>PRIVATE OLD TEXT</s:payload></w:rPr></w:rPrChange>"
        '</w:rPr><w:pPr><w:pPrChange w:id="2"><w:pPr><w:numPr/>'
        "</w:pPr></w:pPrChange></w:pPr>",
    )
    result = read(fixture(content)[0])
    record = result.styles[0]
    assert record.status == "resolved" and record.properties.vanish.value is None
    assert record.properties.vanish.anchor is None
    assert PRIVATE not in repr(result) + repr(record) + repr(record.issues)
    with pytest.raises(FrozenInstanceError):
        result.status = "wrong"
    assert not hasattr(result, "__dict__")
    for field in fields(result):
        assert not isinstance(getattr(result, field.name), (bytes, ET.Element))


@pytest.mark.parametrize(
    "content,code",
    [
        (style("A", '<w:basedOn w:val="missing"/>'), "missing_base_style"),
        (
            style("A", '<w:basedOn w:val="C"/>') + style("C", kind="character"),
            "base_style_type_mismatch",
        ),
        (style("A", '<w:basedOn w:val="A"/>'), "style_cycle"),
        (
            style("A", '<w:basedOn w:val="B"/>')
            + style("B", '<w:basedOn w:val="C"/>')
            + style("C", '<w:basedOn w:val="B"/>'),
            "style_cycle",
        ),
        (
            style("A", '<w:basedOn w:val="B"/>') + style("B", "<w:rPr><w:unknown/></w:rPr>"),
            "unresolved_base_style",
        ),
    ],
)
def test_unresolved_graph_is_not_absent_visibility(content, code):
    result = read(fixture(content)[0])
    record = by_id(result)["A"]
    assert result.status == "ready" and record.status == "blocked" and record.properties is None
    assert len(record.issues) == 1 and record.issues[0].code == code
    assert record.issues[0].anchor == record.anchor and record.issues[0].style_id == "A"


@pytest.mark.parametrize(
    "content",
    [
        '<w:rPr><w:vanish w:val="TRUE"/></w:rPr>',
        '<w:rPr><w:vanish w:val=" true "/></w:rPr>',
        "<w:rPr><w:vanish/><w:vanish/></w:rPr>",
        "<w:rPr><s:vanish/></w:rPr>",
        '<w:rPr><w:vanish s:val="true"/></w:rPr>',
        "<w:rPr><w:vanish>BAD</w:vanish></w:rPr>",
        "<w:rPr><w:vanish/>BAD</w:rPr>",
        '<w:rPr><w:rStyle w:val="x"/></w:rPr>',
        "<w:pPr><w:numPr/></w:pPr>",
        "<w:pPr><w:rPr><w:vanish/></w:rPr></w:pPr>",
        "<w:rPr><w:rPrChange><w:rPr/></w:rPrChange></w:rPr>",
        '<w:rPr><w:rPrChange w:id="x"><w:rPr/></w:rPrChange></w:rPr>',
        '<w:rPr><w:rPrChange w:id="1"><w:pPr/></w:rPrChange></w:rPr>',
        '<w:rPr><w:rPrChange w:id="1"><w:rPr/><w:rPr/></w:rPrChange></w:rPr>',
        '<w:rPr><w:rPrChange w:id="1"><w:rPr/></w:rPrChange>BAD</w:rPr>',
        '<w:basedOn w:val="A"/><w:basedOn w:val="B"/>',
        '<w:uiPriority w:val="-1"/>',
        "<w:unknown/>",
    ],
)
def test_unsupported_current_structure_blocks_only_that_style(content):
    result = read(fixture(style("A", content) + style("B"))[0])
    assert result.status == "ready" and by_id(result)["B"].status == "resolved"
    record = by_id(result)["A"]
    assert record.status == "blocked" and record.properties is None
    assert record.issues[0].code == "unsupported_style_structure"


@pytest.mark.parametrize(
    "content,attrs,code",
    [
        (style() + style(), "", "invalid_style_identity"),
        ('<w:style w:type="other" w:styleId="A"/>', "", "invalid_style_identity"),
        ('<w:style w:type="paragraph"/>', "", "invalid_style_identity"),
        (
            style(attrs='w:default="true"') + style("B", attrs='w:default="1"'),
            "",
            "duplicate_default_style",
        ),
        (style(), 'mc:Ignorable="s"', "unsupported_style_structure"),
        ("<s:style/>", "", "unsupported_style_structure"),
        ("BAD" + style(), "", "unsupported_style_structure"),
        (
            "<w:docDefaults><w:rPrDefault><w:rPr><w:unknown/></w:rPr></w:rPrDefault>"
            "</w:docDefaults>",
            "",
            "unsupported_defaults",
        ),
        ("<w:latentStyles><w:unknown/></w:latentStyles>", "", "unsupported_style_structure"),
    ],
)
def test_global_failure_never_releases_partial_records(content, attrs, code):
    result = read(fixture(content, root_attrs=attrs)[0])
    assert result.status == "blocked" and result.styles == () and result.defaults is None
    assert len(result.issues) == 1 and result.issues[0].code == code
    assert result.issues[0].anchor.path == () and result.issues[0].style_id is None
    assert_digest(result)


@pytest.mark.parametrize("variant", ["orphan", "wrong_mime", "extra", "external", "duplicate"])
def test_relationship_and_content_type_disagreement_is_blocked(variant):
    xml = f'<w:styles xmlns:w="{W}"/>'.encode()
    parts = {"word/styles.xml": xml}
    types = {"word/styles.xml": MIME if variant != "wrong_mime" else "application/xml"}
    link = {"Id": "s", "Type": R + "styles", "Target": "styles.xml"}
    links = [] if variant == "orphan" else [link]
    if variant == "extra":
        parts["word/extra.xml"] = xml
        types["word/extra.xml"] = MIME
    if variant == "external":
        links = [dict(link, Target="https://example.invalid/styles.xml", TargetMode="External")]
    if variant == "duplicate":
        links.append(dict(link, Id="s2"))
    result = read(package("<w:p/>", extra_parts=parts, extra_types=types, links=links)[0])
    assert result.status == "blocked" and result.styles_part is None
    assert result.issues[0].code == "ambiguous_styles_part" and result.issues[0].anchor is None


def test_opaque_definitions_do_not_supply_properties_or_based_on():
    result = read(
        fixture(
            style("T", '<w:basedOn w:val="missing"/><s:unknown/>', kind="table")
            + style("N", kind="numbering")
            + style()
        )[0]
    )
    for identity in ("T", "N"):
        record = by_id(result)[identity]
        assert record.status == "opaque" and record.based_on is None and record.properties is None
        assert record.issues[0].code == "opaque_style_type"
    assert by_id(result)["A"].status == "resolved"


def test_exact_limits_excluded_input_and_chain_depth():
    raw, xml = fixture(style(content="<w:rPr><w:vanish/></w:rPr>"))
    node_count = len(list(ET.fromstring(xml).iter()))
    assert (
        read(raw, limits=api().StyleContextLimits(max_nodes=node_count, max_depth=4)).status
        == "ready"
    )
    for values in ({"max_nodes": node_count - 1}, {"max_depth": 3}):
        with pytest.raises(api().StyleContextError) as caught:
            read(raw, limits=api().StyleContextLimits(**values))
        assert caught.value.code == "style_limit_exceeded"
    chain = "".join(
        style(str(i), (f'<w:basedOn w:val="{i - 1}"/>' if i else "") + "<w:rPr><w:vanish/></w:rPr>")
        for i in range(128)
    )
    assert len(read(fixture(chain)[0]).styles) == 128
    with pytest.raises(api().StyleContextError):
        read(fixture(chain)[0], limits=api().StyleContextLimits(max_chain_depth=127))
    bad = fixture(
        style("A", '<w:basedOn w:val="missing"/>') + style("B", '<w:basedOn w:val="missing"/>')
    )[0]
    assert len(read(bad, limits=api().StyleContextLimits(max_styles=2, max_issues=2)).styles) == 2
    for values in ({"max_styles": 1}, {"max_issues": 1}):
        with pytest.raises(api().StyleContextError):
            read(bad, limits=api().StyleContextLimits(**values))
    for content in (
        style(
            content='<w:rPr><w:rPrChange w:id="1"><w:rPr>'
            + "<w:vanish/>" * 10
            + "</w:rPr></w:rPrChange></w:rPr>"
        ),
        style(kind="table", content="<s:unknown/>" * 10),
    ):
        with pytest.raises(api().StyleContextError):
            read(fixture(content)[0], limits=api().StyleContextLimits(max_nodes=5))


def test_strict_inputs_immutable_limits_and_package_guards():
    raw = fixture(style(), comment=b"PK\x05\x06" + b"\0" * 18)[0]
    assert read(raw).status == "ready"
    for data in (None, bytearray(raw), memoryview(raw), "wrong"):
        with pytest.raises(api().StyleContextError):
            api().read_style_context(data, source_sha256=sha256(raw).hexdigest())
    for field in fields(api().StyleContextLimits):
        for bad in (True, 0, -1, 1.2, field.default + 1):
            with pytest.raises(api().StyleContextError):
                api().StyleContextLimits(**{field.name: bad})
    for kwargs in ({"source_sha256": "A" * 64}, {"source_sha256": None}, {"limits": {}}):
        options = {"source_sha256": sha256(raw).hexdigest(), **kwargs}
        with pytest.raises(api().StyleContextError) as caught:
            api().read_style_context(raw, **options)
        assert caught.value.code == "invalid_input"
    with pytest.raises(api().StyleContextError) as caught:
        api().read_style_context(raw, source_sha256="0" * 64)
    assert caught.value.code == "source_mismatch"
    from ara.docx_package import DocxError

    with pytest.raises(DocxError) as caught:
        read(b"x" * 33554433)
    assert caught.value.code == "package_limit_exceeded"
    with pytest.raises(DocxError):
        read(b"invalid ZIP")


def test_fresh_process_import_and_build_have_no_application_io():
    raw = fixture(style(PRIVATE, "<w:rPr><w:vanish/></w:rPr>"))[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.visibility import read_style_context
s=read_style_context(data,source_sha256=sha256(data).hexdigest())
assert s.status=="ready" and s.styles[0].properties.vanish.value is True
assert "SYNTHETIC_PRIVATE_STYLE" not in repr(s)+repr(s.styles[0])
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
