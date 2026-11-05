"""Whole-input note budgets, source pinning, exact inputs and inert imports."""

import os
import subprocess
import sys
from dataclasses import fields
from importlib import import_module
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from test_docx_note_catalog import api, error, fixture, note, part_xml, payload, read
from test_docx_section_catalog import BASE
from test_docx_visible_main import S


def test_exact_aggregate_xml_note_part_and_manifest_limits():
    raw, parts = fixture(note("2") + note("3", "separator"))
    count = sum(len(list(ET.fromstring(p).iter())) for p in parts.values())
    c = read(raw)
    assert (
        read(
            raw,
            limits=api().NoteLimits(
                max_xml_nodes=count, max_parts=2, max_notes=3, max_manifest_bytes=len(payload(c))
            ),
        )
        == c
    )
    for kw in (
        dict(max_xml_nodes=count - 1),
        dict(max_parts=1),
        dict(max_notes=2),
        dict(max_manifest_bytes=len(payload(c)) - 1),
    ):
        error("note_limit_exceeded", lambda kw=kw: read(raw, limits=api().NoteLimits(**kw)))


def test_unbound_special_and_nested_notes_count_before_any_semantic_dom(monkeypatch):
    parser = import_module("ara.docx_analysis.notes._xml")

    def forbidden(*a, **kw):
        raise AssertionError("DOM before whole-input preflight")

    monkeypatch.setattr(parser, "build_tree", forbidden)
    hidden = '<w:unknown xmlns:huge="' + "x" * 2048 + '">' + note("1") + "</w:unknown>"
    raw, _ = fixture(note("2", "separator", content=hidden), links=[])
    error(
        "note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_xml_characters=1024))
    )
    error("note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_notes=2)))
    error("note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_xml_depth=3)))
    error("note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_parts=1)))
    raw, parts = fixture()
    total = sum(len(list(ET.fromstring(p).iter())) for p in parts.values())
    error(
        "note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_xml_nodes=total - 1))
    )


def test_attribute_text_and_foreign_word_namespace_notes_count():
    raw, _ = fixture(note("2", content='<w:unknown w:val="' + "x" * 2048 + '"/>'))
    error(
        "note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_xml_characters=1024))
    )
    foreign = f'<x:footnote xmlns:x="{S}" x:id="3"><x:p/></x:footnote>'
    raw, _ = fixture(note("2", content=foreign))
    error("note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_notes=2)))


def test_limits_revalidate_exact_types_and_mutated_or_missing_fields():
    for f in fields(api().NoteLimits):
        for v in (True, 0, -1, 1.5, f.default + 1):
            error("invalid_input", lambda f=f, v=v: api().NoteLimits(**{f.name: v}))
    caps = api().NoteLimits()
    object.__setattr__(caps, "max_notes", True)
    error("invalid_input", lambda: read(fixture()[0], limits=caps))
    object.__delattr__(caps, "max_notes")
    error("invalid_input", lambda: read(fixture()[0], limits=caps))
    error("invalid_input", lambda: read(fixture()[0], limits={}))


def test_source_and_archive_bounds_precede_semantic_work(monkeypatch):
    from hashlib import sha256

    from ara.docx_package import DocxError

    raw = fixture()[0]
    for bad in (None, bytearray(raw), "bad"):
        error(
            "invalid_input",
            lambda bad=bad: api().read_note_catalog(bad, source_sha256=sha256(raw).hexdigest()),
        )
    error("invalid_input", lambda: api().read_note_catalog(raw, source_sha256="A" * 64))
    error("source_mismatch", lambda: api().read_note_catalog(raw, source_sha256="0" * 64))

    def forbidden(*a, **kw):
        raise AssertionError("Hash before archive size check")

    monkeypatch.setattr(import_module("ara.docx_analysis.notes._read"), "sha256", forbidden)
    with pytest.raises(DocxError) as caught:
        api().read_note_catalog(b"x" * 33554433, source_sha256="0" * 64)
    assert caught.value.code == "package_limit_exceeded"


def test_many_unlinked_parts_do_not_escape_part_budget():
    extras = {f"custom/Spare{i}.xml": part_xml(note()) for i in range(3)}
    raw, _ = fixture(extras=extras, types={name: BASE + "footnotes+xml" for name in extras})
    error("note_limit_exceeded", lambda: read(raw, limits=api().NoteLimits(max_parts=4)))
    assert len(read(raw, limits=api().NoteLimits(max_parts=5)).parts) == 5


def test_fresh_process_reads_only_given_bytes_without_application_io():
    raw = fixture()[0]
    script = """
import builtins,io,os,socket,subprocess,sys
from pathlib import Path
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=forbidden
from ara.docx_analysis.notes import read_note_catalog
c=read_note_catalog(data,source_sha256=sha256(data).hexdigest())
assert c.status=="indexed" and len(c.parts)==2 and all(p.linked for p in c.parts)
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


def test_transitional_and_strict_links_cannot_bind_the_same_kind_twice():
    from test_docx_visible_main import SR, R

    links = [
        {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        {"Id": "StrictF", "Type": SR + "footnotes", "Target": "Foot.xml"},
    ]
    c = read(fixture(links=links)[0])
    assert c.status == "blocked" and c.parts == ()
    assert c.issues[0].code == "unresolved_note_relationship"


def test_unlinked_malformed_part_is_not_silently_classified_as_safe_orphan():
    raw, _ = fixture(
        extras={"custom/Spare.xml": part_xml(note("2", "unknown"))},
        types={"custom/Spare.xml": BASE + "footnotes+xml"},
    )
    c = read(raw)
    assert c.status == "blocked" and c.parts == ()
    issue = c.issues[0]
    assert issue.code == "invalid_note_markup"
    assert issue.anchor.part_name == "custom/Spare.xml" and issue.anchor.path == (0,)


@pytest.mark.parametrize("identity", [" 2", "2 ", "\u0662"])
def test_noncanonical_lexical_numeric_forms_do_not_gain_a_target(identity):
    c = read(fixture(note("1") + note(identity))[0])
    assert c.status == "blocked" and c.parts == ()
    assert c.issues[0].code == "invalid_note_markup"
    assert c.issues[0].anchor.path == (1,)


def test_special_type_does_not_create_a_separate_id_namespace():
    c = read(fixture(note("+2", "separator") + note("02", "normal"))[0])
    assert c.status == "blocked" and c.parts == ()
    assert c.issues[0].code == "duplicate_note_id"
    assert c.issues[0].anchor.path == (1,)
