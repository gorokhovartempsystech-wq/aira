"""Bounded structural catalog rejects unsafe inputs before semantic allocation."""

import io
import socket
import zipfile
from dataclasses import fields
from hashlib import sha256
from pathlib import Path

import pytest
from docx_package_fixtures import build_package
from test_docx_move_catalog import api, group, read, run, source

from ara.docx_package import DocxError


def error(code, operation):
    with pytest.raises(api().MoveCatalogError) as caught:
        operation()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE_MOVE" not in str(caught.value)


def test_invalid_identity_and_limits():
    raw, _ = source()
    for data, digest in (
        (None, "0" * 64),
        (bytearray(raw), sha256(raw).hexdigest()),
        (raw, None),
        (raw, "A" * 64),
    ):
        error("invalid_input", lambda: api().read_move_catalog(data, source_sha256=digest))
    error("source_mismatch", lambda: api().read_move_catalog(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: read(raw, limits=object()))
    for field in fields(api().MoveLimits):
        for invalid in (0, -1, True, field.default + 1):
            error("invalid_input", lambda: api().MoveLimits(**{field.name: invalid}))
    limits = api().MoveLimits()
    object.__setattr__(limits, "max_ranges", True)
    error("invalid_input", lambda: read(raw, limits=limits))


@pytest.mark.parametrize(
    "name,body,value",
    [
        ("max_xml_nodes", "<w:p>" + run() + "</w:p>", 2),
        ("max_xml_depth", "<w:p><w:del w:id='1'>" + run() + "</w:del></w:p>", 3),
        (
            "max_xml_characters",
            '<w:p><w:del w:id="1">' + run("hidden" * 100) + "</w:del></w:p>",
            100,
        ),
        ("max_xml_characters", '<w:p w:synthetic="' + "a" * 300 + '"/>', 100),
        ("max_ranges", "<w:p>" + group() + group("To") + "</w:p>", 1),
        (
            "max_members",
            '<w:p><s:opaque><w:moveFrom w:id="1"/><w:moveTo w:id="2"/></s:opaque></w:p>',
            1,
        ),
    ],
)
def test_every_main_node_is_bounded_before_semantic_dom(monkeypatch, name, body, value):
    from ara.docx_package.projection import _parse

    raw, _ = source(body)
    a = api()

    def forbidden(*args, **kwargs):
        raise AssertionError("Semantic DOM allocated before failed preflight")

    monkeypatch.setattr(_parse, "_BoundedBuilder", forbidden)
    error("move_limit_exceeded", lambda: read(raw, limits=a.MoveLimits(**{name: value})))


def test_legal_fake_eocd_comment_is_same_catalog():
    raw, _ = source(comment=b"PK\x05\x06" + b"\0" * 18)
    assert read(raw).status == "indexed"


def test_dtd_in_main_is_rejected_by_package_boundary():
    raw, _ = source()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    original = parts["custom/Moves.xml"]
    declaration, content = original.split(b"?>", 1)
    parts["custom/Moves.xml"] = (
        declaration + b'?><!DOCTYPE document [<!ENTITY private "bad">]>' + content
    )
    with pytest.raises(DocxError):
        read(build_package(parts))


def test_factory_does_not_read_files_or_network(monkeypatch):
    a = api()
    raw, _ = source()

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure catalog touched external IO")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert a.read_move_catalog(raw, source_sha256=sha256(raw).hexdigest()).status == "indexed"


@pytest.mark.parametrize(
    "changed",
    [
        '<w:p><w:moveFrom w:id="1"><w:moveTo w:id="2">' + run() + "</w:moveTo></w:moveFrom></w:p>",
        '<w:p><w:moveFromRangeStart w:id="0" w:name="a"/><w:moveFrom w:id="1">'
        + run()
        + '</w:moveFrom><w:moveFromRangeEnd w:id="1"/></w:p>',
        "<w:p>" + group() + '<w:moveFromRangeEnd w:id="0"/>' + group("To") + "</w:p>",
        "<w:p>" + group(name="Name") + group("To", name="name") + "</w:p>",
        "<w:p>" + group(name="é") + group("To", name="é") + "</w:p>",
        "<w:p>"
        + group().replace("w:name=", 'w:displacedByCustomXml="next" w:name=', 1)
        + group("To")
        + "</w:p>",
        "<w:p>"
        + group().replace("w:moveFromRangeStart", "s:moveFromRangeStart", 1)
        + group("To")
        + "</w:p>",
    ],
)
def test_no_guessing_normalization_nested_members_or_extra_ends(changed):
    c = read(source(changed)[0])
    assert c.status == "blocked" and not c.pairs


def test_unsupported_main_move_does_not_get_hidden_by_other_parts():
    extras = {"custom/extra.xml": b"<root/>"}
    raw, _ = source("<w:p><s:opaque>" + group() + "</s:opaque></w:p>", extra_parts=extras)
    assert read(raw).status == "blocked"


def test_unused_namespace_declaration_is_inside_character_budget(monkeypatch):
    from ara.docx_package.projection import _parse

    raw, _ = source('<w:p><s:opaque xmlns:large="urn:synthetic:' + "x" * 2000 + '"/></w:p>')
    a = api()

    def forbidden(*args, **kwargs):
        raise AssertionError("Namespace allocation escaped preflight")

    monkeypatch.setattr(_parse, "_BoundedBuilder", forbidden)
    error("move_limit_exceeded", lambda: read(raw, limits=a.MoveLimits(max_xml_characters=1000)))


def test_comments_and_root_metadata_do_not_shift_element_only_addresses():
    raw, xml = source(
        before_body='<!-- synthetic --><?synthetic note?><w:background w:color="FFFFFF"/>',
        comment=b"PK\x05\x06" + b"\0" * 18,
    )
    c = read(raw)
    assert c.status == "indexed"
    (pair,) = c.pairs
    assert pair.source.start.path == (1, 0, 0)
    assert pair.destination.start.path == (1, 0, 3)


def test_word_namespace_cannot_change_inside_a_move_range():
    strict = "http://purl.oclc.org/ooxml/wordprocessingml/main"
    body = (
        "<w:p>"
        + group().replace("<w:moveFrom w:id=", f'<w:moveFrom xmlns:w="{strict}" w:id=')
        + group("To")
        + "</w:p>"
    )
    c = read(source(body)[0])
    assert c.status == "blocked" and c.issues[0].code == "unsupported_move_context"
