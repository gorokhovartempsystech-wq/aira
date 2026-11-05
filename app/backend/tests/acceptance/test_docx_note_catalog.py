"""Physical note definitions, original identities, and explicit main relationships."""

import io
import json
import zipfile
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256
from importlib import import_module
from xml.etree import ElementTree as ET

import pytest
from docx_package_fixtures import build_package, relationships_xml
from test_docx_move_catalog import resolve
from test_docx_section_catalog import BASE
from test_docx_table_catalog import paragraph
from test_docx_visible_main import SR, R, S, W, source


def api():
    return import_module("ara.docx_analysis.notes")


def note(identity="2", note_type=None, *, kind="footnote", content=None, attrs=""):
    type_attr = "" if note_type is None else f' w:type="{note_type}"'
    return (
        f'<w:{kind} w:id="{identity}"{type_attr}{attrs}>'
        + (paragraph("Note 🧪") if content is None else content)
        + f"</w:{kind}>"
    )


def part_xml(content, kind="footnote", *, strict=False, encoding="utf-8"):
    ns = S if strict else W
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:{kind}s xmlns:w="{ns}">{content}</w:{kind}s>'
    ).encode(encoding)


def fixture(
    foot=None, end=None, *, strict=False, encoding="utf-8", links=None, types=None, extras=None
):
    rel = SR if strict else R
    parts = {
        "custom/Foot.xml": part_xml(
            note() if foot is None else foot, strict=strict, encoding=encoding
        ),
        "custom/End.xml": part_xml(
            note("2", kind="endnote") if end is None else end,
            "endnote",
            strict=strict,
            encoding=encoding,
        ),
    }
    content_types = {
        "custom/Foot.xml": BASE + "footnotes+xml",
        "custom/End.xml": BASE + "endnotes+xml",
    }
    content_types.update(types or {})
    parts.update(extras or {})
    links = (
        links
        if links is not None
        else [
            {"Id": "F", "Type": rel + "footnotes", "Target": "Foot.xml"},
            {"Id": "E", "Type": rel + "endnotes", "Target": "End.xml"},
        ]
    )
    raw, _ = source(
        paragraph("Body"),
        strict=strict,
        encoding=encoding,
        extra_parts=parts,
        extra_types=content_types,
        links=links,
    )
    return raw, parts


def read(raw, **kwargs):
    return api().read_note_catalog(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def payload(c):
    d = asdict(c)
    d.pop("catalog_sha256")
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def error(code, call):
    with pytest.raises(api().NoteCatalogError) as caught:
        call()
    assert caught.value.code == code


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_physical_order_types_canonical_ids_and_original_part_anchors(strict, encoding):
    foot = (
        note("-1")
        + note("00", "normal")
        + note("9", "separator")
        + note("10", "continuationSeparator")
        + note("11", "continuationNotice")
    )
    raw, parts = fixture(foot, strict=strict, encoding=encoding)
    c = read(raw)
    assert (
        c.status == "indexed"
        and c.profile == "docx-notes/original-definitions-v1"
        and c.issues == ()
    )
    assert [p.part_name for p in c.parts] == ["custom/End.xml", "custom/Foot.xml"]
    assert [p.kind for p in c.parts] == ["endnote", "footnote"] and all(p.linked for p in c.parts)
    f = c.parts[1]
    assert [d.note_id for d in f.definitions] == [-1, 0, 9, 10, 11]
    assert [d.note_type for d in f.definitions] == [
        "normal",
        "normal",
        "separator",
        "continuationSeparator",
        "continuationNotice",
    ]
    assert f.root_anchor.path == () and f.root_anchor.part_name == f.part_name
    root = ET.fromstring(parts[f.part_name])
    for i, d in enumerate(f.definitions):
        assert d.anchor.path == (i,) and d.anchor.source_sha256 == c.source_sha256
        assert resolve(root, d.anchor).tag.endswith("}footnote")
    assert c.catalog_sha256 == sha256(payload(c)).hexdigest() and read(raw) == c
    assert not hasattr(c, "analysis_text") and not hasattr(c, "complete")
    assert "Note 🧪" not in repr(c) + repr(c.parts) + repr(f.definitions)
    with pytest.raises(FrozenInstanceError):
        f.linked = False
    assert not hasattr(f, "__dict__") and sha256(raw).hexdigest() == c.source_sha256


def test_absent_and_empty_parts_have_no_fabricated_note():
    c = read(source(paragraph("Body"))[0])
    assert c.status == "absent" and c.parts == () and c.issues == ()
    c = read(fixture("", "")[0])
    assert c.status == "indexed" and len(c.parts) == 2
    assert all(p.definitions == () for p in c.parts)


def test_unbound_parts_are_metadata_not_active_stories():
    raw, _ = fixture(links=[])
    c = read(raw)
    assert c.status == "indexed" and not any(p.linked for p in c.parts)
    assert len(c.parts) == 2 and not hasattr(c, "complete")
    extra = {"custom/Spare.xml": part_xml(note("2"))}
    raw, _ = fixture(extras=extra, types={"custom/Spare.xml": BASE + "footnotes+xml"})
    c = read(raw)
    assert [p.linked for p in c.parts] == [True, True, False]
    assert [p.definitions[0].note_id for p in c.parts] == [2, 2, 2]


def test_relationship_owned_by_another_part_does_not_bind_main_notes():
    raw, _ = fixture(links=[])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["custom/_rels/End.xml.rels"] = relationships_xml(
        [{"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"}]
    )
    c = read(build_package(parts))
    assert c.status == "indexed" and not any(p.linked for p in c.parts)


@pytest.mark.parametrize("ids", [("0", "+00"), ("-0", "00"), ("2", "02"), ("-2", "-02")])
def test_duplicate_normalized_note_ids_are_atomic_even_with_good_part_prefix(ids):
    c = read(fixture(note(ids[0]) + note(ids[1]))[0])
    assert c.status == "blocked" and c.parts == () and c.issues[0].code == "duplicate_note_id"


@pytest.mark.parametrize(
    "links",
    [
        [
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
            {"Id": "F2", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
        [{"Id": "F", "Type": R + "footnotes", "Target": "End.xml"}],
        [
            {
                "Id": "F",
                "Type": R + "footnotes",
                "Target": "https://invalid.example",
                "TargetMode": "External",
            }
        ],
    ],
)
def test_ambiguous_wrong_kind_or_external_main_relationships_are_not_followed(links):
    c = read(fixture(links=links)[0])
    assert (
        c.status == "blocked"
        and c.parts == ()
        and c.issues[0].code == "unresolved_note_relationship"
    )


def test_wrong_mime_relationship_target_is_not_guessed_from_xml_root():
    c = read(fixture(types={"custom/Foot.xml": "application/xml"})[0])
    assert (
        c.status == "blocked"
        and c.parts == ()
        and c.issues[0].code == "unresolved_note_relationship"
    )


@pytest.mark.parametrize(
    "foot",
    [
        note("BAD"),
        note("9" * 21),
        note("1", "unknown"),
        note("1", content=""),
        "<w:footnote>" + paragraph("Missing id") + "</w:footnote>",
        note("1", attrs=' w:extra="X"'),
        note("1", content="RAW TEXT" + paragraph("Nested")),
        note("1") + "<w:unknown/>",
        note("1", kind="endnote"),
        f'<x:footnote xmlns:x="{S}" x:id="2"><x:p/></x:footnote>',
    ],
)
def test_malformed_current_definition_and_root_children_block_without_partial_catalog(foot):
    c = read(fixture(foot)[0])
    assert c.status == "blocked" and c.parts == () and c.issues[0].code == "invalid_note_markup"


def test_opaque_payload_never_activates_nested_note_definitions_or_exposes_text():
    foot = note("2", content="<w:unknown>" + note("2") + "</w:unknown>")
    c = read(fixture(foot)[0])
    assert c.status == "indexed" and len(c.parts[1].definitions) == 1
    assert c.parts[1].definitions[0].anchor.path == (0,)
    assert "Note 🧪" not in repr(c)


def test_root_kind_namespace_and_attributes_must_match_the_typed_part():
    raw, _ = fixture()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    for root in (
        b'<w:endnotes xmlns:w="' + W.encode() + b'"/>',
        b'<x:footnotes xmlns:x="urn:other"/>',
        b'<w:footnotes xmlns:w="' + W.encode() + b'" w:extra="1"/>',
    ):
        changed = dict(parts)
        changed["custom/Foot.xml"] = root
        c = read(build_package(changed))
        assert c.status == "blocked" and c.parts == () and c.issues[0].code == "invalid_note_markup"
