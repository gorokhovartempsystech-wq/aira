"""Section proof input bounds, provenance, namespace confusion and inert imports."""

import io
import os
import subprocess
import sys
import zipfile
from dataclasses import fields
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from docx_package_fixtures import build_package
from test_docx_section_catalog import (
    api,
    boundary,
    error,
    fixture,
    payload,
    previous,
    read,
    reference,
    section,
)
from test_docx_visible_main import S


def test_exact_whole_xml_reference_section_and_manifest_budgets():
    raw, xml = fixture(boundary(section(reference())) + section(reference("First")))
    c = read(raw)
    nodes = len(list(ET.fromstring(xml).iter()))
    limits = api().SectionLimits(
        max_sections=2, max_references=2, max_xml_nodes=nodes, max_manifest_bytes=len(payload(c))
    )
    assert read(raw, limits=limits) == c
    for kw in (
        dict(max_sections=1),
        dict(max_references=1),
        dict(max_xml_nodes=nodes - 1),
        dict(max_manifest_bytes=len(payload(c)) - 1),
    ):
        error("section_limit_exceeded", lambda kw=kw: read(raw, limits=api().SectionLimits(**kw)))
    # A physical boundary plus implicit final section consumes two section records.
    error(
        "section_limit_exceeded",
        lambda: read(fixture(boundary(section()))[0], limits=api().SectionLimits(max_sections=1)),
    )


def test_settings_and_excluded_history_count_before_any_semantic_tree(monkeypatch):
    from importlib import import_module

    parser = import_module("ara.docx_analysis.sections._xml")

    def forbidden(*a, **kw):
        raise AssertionError("DOM before whole-input preflight")

    monkeypatch.setattr(parser, "build_tree", forbidden)
    raw, _ = fixture(
        section(history=previous(payload='<w:unknown xmlns:huge="' + "x" * 2048 + '"/>'))
    )
    error(
        "section_limit_exceeded",
        lambda: read(raw, limits=api().SectionLimits(max_xml_characters=1024)),
    )
    raw, _ = fixture(settings="<w:compat>" + "<w:unknown/>" * 50 + "</w:compat>")
    error("section_limit_exceeded", lambda: read(raw, limits=api().SectionLimits(max_xml_nodes=50)))


def test_history_hidden_sections_and_references_have_whole_input_caps():
    hidden = previous(payload=section(reference() + reference("First")))
    raw = fixture(section(history=hidden))[0]
    error("section_limit_exceeded", lambda: read(raw, limits=api().SectionLimits(max_references=1)))
    error("section_limit_exceeded", lambda: read(raw, limits=api().SectionLimits(max_sections=2)))
    raw = fixture(boundary(section(history=previous()) + previous("pPr")))[0]
    error("section_limit_exceeded", lambda: read(raw, limits=api().SectionLimits(max_histories=1)))


def test_limits_revalidate_mutated_exact_types_and_missing_fields():
    for f in fields(api().SectionLimits):
        for v in (True, 0, -1, 1.5, f.default + 1):
            error("invalid_input", lambda f=f, v=v: api().SectionLimits(**{f.name: v}))
    caps = api().SectionLimits()
    object.__setattr__(caps, "max_sections", True)
    error("invalid_input", lambda: read(fixture()[0], limits=caps))
    object.__delattr__(caps, "max_sections")
    error("invalid_input", lambda: read(fixture()[0], limits=caps))
    error("invalid_input", lambda: read(fixture()[0], limits={}))


def test_source_hash_and_archive_size_precede_semantic_work(monkeypatch):
    from importlib import import_module

    from ara.docx_package import DocxError

    raw = fixture()[0]
    for bad in (None, bytearray(raw), "bad"):
        error(
            "invalid_input",
            lambda bad=bad: api().read_section_catalog(bad, source_sha256=sha256(raw).hexdigest()),
        )
    error("invalid_input", lambda: api().read_section_catalog(raw, source_sha256="A" * 64))
    error("source_mismatch", lambda: api().read_section_catalog(raw, source_sha256="0" * 64))

    def forbidden(*a, **kw):
        raise AssertionError("Hash before archive size check")

    monkeypatch.setattr(import_module("ara.docx_analysis.sections._read"), "sha256", forbidden)
    with pytest.raises(DocxError) as caught:
        api().read_section_catalog(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


@pytest.mark.parametrize(
    "body",
    [
        section(props=f'<x:titlePg xmlns:x="{S}"/>'),
        f'<x:sectPr xmlns:x="{S}"> ' + reference() + "</x:sectPr>",
        section(f'<x:headerReference xmlns:x="{S}" r:id="H" x:type="default"/>'),
        "<w:p><w:pPr/>" + "<w:pPr>" + section(reference()) + "</w:pPr></w:p>",
        "<w:p><w:r/>" + "<w:pPr>" + section(reference()) + "</w:pPr></w:p>",
    ],
)
def test_foreign_word_namespace_and_noncurrent_properties_never_bind(body):
    c = read(fixture(body)[0])
    assert c.status == "blocked" and c.sections == c.stories == c.histories == ()


def test_story_root_and_content_are_not_claimed_as_read_or_rewritten():
    raw = fixture()[0]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["custom/H.xml"] = b'<unknown xmlns="urn:synthetic">Unparsed story</unknown>'
    changed = build_package(parts)
    c = read(changed)
    assert c.status == "indexed" and c.stories[0].root_anchor.part_name == "custom/H.xml"
    assert not hasattr(c, "complete") and not hasattr(c, "analysis_text")
    assert sha256(changed).hexdigest() == c.source_sha256
    assert read(raw).catalog_sha256 != c.catalog_sha256


def test_fresh_process_reads_only_bytes_not_application_io():
    raw = fixture(boundary(section(reference())) + section())[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.sections import read_section_catalog
c=read_section_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="indexed" and len(c.sections)==2 and len(c.stories)==1
assert c.sections[1].bindings[0].origin_section==0
assert not hasattr(c,"complete")
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


def test_inactive_first_definition_survives_an_intervening_omitted_definition():
    body = boundary(section(reference("First", variant="first")))
    body += boundary(section()) + section(props="<w:titlePg/>")
    c = read(fixture(body)[0])
    assert c.status == "indexed" and len(c.sections) == 3
    assert len(c.sections[0].bindings) == len(c.sections[1].bindings) == 2
    first = c.sections[2].bindings[1]
    assert first.variant == "first" and first.part_name == "custom/First.xml"
    assert first.origin_section == 0
    assert first.definition_anchor == c.sections[0].references[0].anchor
    assert [s.part_name for s in c.stories] == ["custom/First.xml"]


def test_xml_budget_is_aggregate_across_main_and_settings():
    raw, xml = fixture(settings="<w:evenAndOddHeaders/>")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        settings = z.read("custom/Settings.xml")
    total = len(list(ET.fromstring(xml).iter())) + len(list(ET.fromstring(settings).iter()))
    assert read(raw, limits=api().SectionLimits(max_xml_nodes=total)) == read(raw)
    error(
        "section_limit_exceeded",
        lambda: read(raw, limits=api().SectionLimits(max_xml_nodes=total - 1)),
    )


def test_reference_id_owned_by_another_story_cannot_resolve_main_reference():
    from docx_package_fixtures import relationships_xml
    from test_docx_visible_main import R

    raw = fixture(section(reference("otherStoryId")), links=[])[0]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["custom/_rels/H.xml.rels"] = relationships_xml(
        [{"Id": "otherStoryId", "Type": R + "header", "Target": "First.xml"}]
    )
    c = read(build_package(parts))
    assert c.status == "blocked" and c.issues[0].code == "unresolved_section_reference"
    assert c.sections == c.stories == c.histories == ()


@pytest.mark.parametrize("change", ["foreign_root", "external_link", "second_settings"])
def test_unresolved_settings_never_default_silently(change):
    from docx_package_fixtures import relationships_xml
    from test_docx_section_catalog import BASE
    from test_docx_visible_main import R, W

    raw = fixture(settings="<w:evenAndOddHeaders/>")[0]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    if change == "foreign_root":
        parts["custom/Settings.xml"] = parts["custom/Settings.xml"].replace(W.encode(), S.encode())
    elif change == "external_link":
        parts["custom/_rels/Main.xml.rels"] = relationships_xml(
            [
                {
                    "Id": "settings",
                    "Type": R + "settings",
                    "Target": "https://invalid.example",
                    "TargetMode": "External",
                },
            ]
        )
    else:
        parts["custom/Settings2.xml"] = parts["custom/Settings.xml"]
        types = ET.fromstring(parts["[Content_Types].xml"])
        ET.SubElement(
            types,
            types.tag.removesuffix("Types") + "Override",
            PartName="/custom/Settings2.xml",
            ContentType=BASE + "settings+xml",
        )
        parts["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8")
    c = read(build_package(parts))
    assert c.status == "blocked" and c.issues[0].code == "unresolved_section_settings"
    assert c.sections == c.stories == c.histories == () and c.even_and_odd is None
