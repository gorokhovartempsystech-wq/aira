"""Synthetic embedded fonts stay opaque and survive checking and manual edits."""

import json
from xml.etree import ElementTree as ET

import pytest
from docx_package_fixtures import relationships_xml
from test_docx_visible_main import SR, R, S, W
from test_docx_visible_main import source as minimal
from test_docx_visible_style_lists import repack
from test_docx_visible_word import alter, blocked, build, original, parts
from test_docx_word_integration import bundle

from ara.docx_analysis import storage_codec
from ara.docx_analysis.visible_word import map_word_span
from ara.docx_package.editing import TextEdit, export_docx

TABLE = "custom/fontTable.xml"
LINKS = "custom/_rels/fontTable.xml.rels"
TTF = "application/x-font-ttf"
OBFUSCATED = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
FONT_KEY = "{12345678-1234-4234-8234-123456789abc}"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
TEXT = "Система сохраняет документ😀."
SLOTS = ("embedRegular", "embedBold", "embedItalic", "embedBoldItalic")


def source(*, strict=False, mime=TTF):
    word, rel = (S, SR) if strict else (W, R)
    body = (
        f'<w:p xmlns:w14="{W14}" w14:paraId="1234ABCD" w14:textId="76543210">'
        '<w:bookmarkStart w:id="1" w:name="Section" w:colFirst="0" w:colLast="0"/>'
        '<w:r><w:rPr><w:b/><w:rtl w:val="0"/></w:rPr>'
        f'<w:t xml:space="preserve">{TEXT}</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>'
    )
    slots = "".join(
        f'<w:{name} r:id="f{i}" w:fontKey="{FONT_KEY}" w:subsetted="0"/>'
        for i, name in enumerate(SLOTS)
    )
    entries = {
        TABLE: (
            f'<w:fonts xmlns:w="{word}" xmlns:r="{rel.rstrip("/")}">'
            f'<w:font w:name="Synthetic">{slots}</w:font></w:fonts>'
        ).encode(),
        LINKS: relationships_xml(
            [{"Id": f"f{i}", "Type": rel + "font", "Target": f"fonts/{i}.ttf"} for i in range(4)]
        ),
    }
    # These inert synthetic bytes test preservation, not font decoding or rendering.
    blobs = {
        f"custom/fonts/{i}.ttf": b"\x00\x01\x00\x00SYNTHETIC-FONT-" + bytes([i]) for i in range(4)
    }
    entries.update(blobs)
    raw, _ = minimal(
        body,
        strict=strict,
        extra_parts=entries,
        extra_types={
            TABLE: "application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml",
            **dict.fromkeys(blobs, mime),
        },
        links=[{"Id": "fonts", "Type": rel + "fontTable", "Target": "fontTable.xml"}],
    )
    return raw


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("mime", [TTF, OBFUSCATED])
def test_all_font_slots_read_map_check_and_export_without_changing_format(strict, mime):
    raw = source(strict=strict, mime=mime)
    before = parts(raw)
    snapshot = build(raw)
    assert snapshot.complete and snapshot.analysis_text == TEXT
    assert sum(c.code == "embedded_font_resource" for c in snapshot.coverage) == 4
    original(raw, snapshot)
    src, attempt, result = bundle(raw)
    assert src.source_data == raw
    assert storage_codec.restore_source(src).snapshot == snapshot
    assert storage_codec.restore_result(src, attempt, result).wire_json == result.result_data
    # This explicit fixture validates the result path, not real ML inference.
    assert json.loads(result.result_data)["findings"]
    assert export_docx(raw, ()) == raw
    fragment = snapshot.fragments[0]
    mapped = map_word_span(
        raw,
        snapshot,
        fragment_id=fragment.fragment_id,
        start=0,
        end=len(TEXT),
        quote=TEXT,
    )
    assert len(mapped.slices) == 1
    replacement = "Система сохраняет изменённый документ😀."
    edited = export_docx(raw, (TextEdit(mapped.slices[0].anchor, TEXT, replacement),))
    after = parts(edited)
    assert before.keys() == after.keys()
    assert all(after[name] == value for name, value in before.items() if name != "custom/Main.xml")
    assert after["custom/Main.xml"] == before["custom/Main.xml"].replace(
        TEXT.encode(), replacement.encode()
    )
    assert build(edited).analysis_text == replacement
    assert parts(raw) == before


@pytest.mark.parametrize(
    "fault",
    [
        "missing_id",
        "unknown_id",
        "bad_key",
        "bad_subset",
        "foreign_id",
        "unknown_attribute",
        "child",
        "text",
        "duplicate_slot",
    ],
)
def test_malformed_font_slots_refuse_atomically(fault):
    def change(root):
        font = root[0]
        node = font[0]
        ns = "{" + W + "}"
        rid = "{" + R.rstrip("/") + "}id"
        if fault == "missing_id":
            node.attrib.pop(rid)
        elif fault == "unknown_id":
            node.set(rid, "missing")
        elif fault == "bad_key":
            node.set(ns + "fontKey", "invalid")
        elif fault == "bad_subset":
            node.set(ns + "subsetted", "maybe")
        elif fault == "foreign_id":
            node.set("{urn:unproved}id", node.attrib.pop(rid))
        elif fault == "unknown_attribute":
            node.set(ns + "unknown", "1")
        elif fault == "child":
            ET.SubElement(node, ns + "t").text = "Hidden requirement"
        elif fault == "text":
            node.text = "Hidden requirement"
        else:
            font.append(ET.fromstring(ET.tostring(node)))

    blocked(alter(source(), TABLE, change))


def test_multiple_slots_can_reference_one_preserved_font_resource():
    raw = alter(source(), LINKS, lambda root: [n.set("Target", "fonts/0.ttf") for n in root])
    entries = parts(raw)
    for i in range(1, 4):
        del entries[f"custom/fonts/{i}.ttf"]
    # Remove declarations for the deliberately removed synthetic resources too.
    root = ET.fromstring(entries["[Content_Types].xml"])
    for node in list(root):
        if node.get("PartName") in {f"/custom/fonts/{i}.ttf" for i in range(1, 4)}:
            root.remove(node)
    entries["[Content_Types].xml"] = ET.tostring(root)
    raw = repack(entries)
    snapshot = build(raw)
    assert snapshot.complete and snapshot.analysis_text == TEXT
    assert sum(c.code == "embedded_font_resource" for c in snapshot.coverage) == 1
    original(raw, snapshot)


def test_unreferenced_font_blob_is_not_silently_excluded():
    raw = alter(source(), TABLE, lambda root: root[0].remove(root[0][-1]))
    raw = alter(raw, LINKS, lambda root: root.remove(root[-1]))
    blocked(raw)


@pytest.mark.parametrize(
    "fault",
    ["external", "wrong_type", "unused", "another_owner", "outgoing", "wrong_mime", "missing_key"],
)
def test_font_resource_roles_are_proven_instead_of_trusting_mime(fault):
    raw = source(mime=OBFUSCATED if fault == "missing_key" else TTF)
    if fault in {"external", "wrong_type", "unused"}:

        def change(root):
            node = root[0]
            if fault == "external":
                node.set("TargetMode", "External")
                node.set("Target", "https://invalid.example/never-fetch.ttf")
            elif fault == "wrong_type":
                node.set("Type", R + "image")
            else:
                node.set("Id", "unreferenced")

        raw = alter(raw, LINKS, change)
    elif fault == "wrong_mime":

        def change(root):
            for node in root:
                if node.get("PartName") == "/custom/fonts/0.ttf":
                    node.set("ContentType", "application/xml")

        # Keep XML well formed so the refusal comes from font-role proof.
        entries = parts(raw)
        entries["custom/fonts/0.ttf"] = b"<unproved/>"
        raw = alter(repack(entries), "[Content_Types].xml", change)
    elif fault == "missing_key":
        raw = alter(raw, TABLE, lambda root: root[0][0].attrib.pop("{" + W + "}fontKey"))
    else:
        entries = parts(raw)
        owner = (
            "custom/_rels/Main.xml.rels"
            if fault == "another_owner"
            else "custom/fonts/_rels/0.ttf.rels"
        )
        root = (
            ET.fromstring(entries[owner])
            if owner in entries
            else ET.Element(
                "{http://schemas.openxmlformats.org/package/2006/relationships}Relationships"
            )
        )
        ET.SubElement(
            root,
            "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship",
            {
                "Id": "extra",
                "Type": R + "font",
                "Target": "fonts/0.ttf" if fault == "another_owner" else "../fontTable.xml",
            },
        )
        entries[owner] = ET.tostring(root)
        raw = repack(entries)
    blocked(raw)
