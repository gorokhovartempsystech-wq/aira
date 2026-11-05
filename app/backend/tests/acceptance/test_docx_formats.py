"""Frozen D03-12 formatting semantics, native numbering and preservation."""

import importlib
import io
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.projection import SourceAnchor, project_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
ROOT = Path(__file__).resolve().parents[2]


def api():
    return importlib.import_module("ara.docx_package.formatting")


def raw(*styles):
    return create_docx(
        tuple(
            NewParagraph(f"  paragraph {i} 😀 &  ", style)
            for i, style in enumerate(styles or ("body",) * 5)
        )
    )


def command(data, index=0, style="Normal", kind="none", identity=None):
    p = project_docx(data).blocks[index]
    return api().ParagraphFormat(p.anchor, p.text, style, kind, identity)


def parts(data):
    with ZipFile(io.BytesIO(data)) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def replace_parts(data, edits):
    out = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as a, ZipFile(out, "w") as b:
        for info in a.infolist():
            b.writestr(info, edits.get(info.filename, a.read(info)))
    return out.getvalue()


def rejects(call, code="invalid_input"):
    with pytest.raises(api().FormattingError) as caught:
        call()
    assert caught.value.code == code
    assert str(caught.value) == caught.value.message and caught.value.message
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize("style", ["Title", "Heading1", "Heading2", "Heading3", None])
def test_style_changes_keep_text_parts_and_exact_run_xml(style):
    data = raw()
    changed = api().export_formats(data, (command(data, style=style),))
    before, after = project_docx(data), project_docx(changed)
    assert [p.text for p in before.blocks] == [p.text for p in after.blocks]
    assert after.blocks[0].style_id == style
    a, b = parts(data), parts(changed)
    assert set(a) == set(b)
    assert all(a[n] == b[n] for n in a if n != "word/document.xml")
    for original in ET.fromstring(a["word/document.xml"]).findall(".//w:r", NS):
        assert ET.tostring(original) in [
            ET.tostring(r) for r in ET.fromstring(b["word/document.xml"]).findall(".//w:r", NS)
        ]


def test_same_style_and_empty_batch_are_byte_identical():
    data = raw()
    assert api().export_formats(data, ()) == data
    assert api().export_formats(data, (command(data),)) == data


def test_other_paragraph_properties_are_not_removed():
    data = raw()
    a = parts(data)
    old = b'<w:pStyle w:val="Normal"/>'
    extras = b'<w:keepNext/><w:spacing w:before="360"/><w:ind w:left="100"/><w:jc w:val="center"/>'
    data = replace_parts(
        data, {"word/document.xml": a["word/document.xml"].replace(old, old + extras, 1)}
    )
    changed = api().export_formats(data, (command(data, style="Heading2"),))
    main = parts(changed)["word/document.xml"]
    assert extras in main
    assert [p.text for p in project_docx(data).blocks] == [
        p.text for p in project_docx(changed).blocks
    ]


def test_native_lists_group_restart_and_continue_without_literal_markers():
    data = raw()
    commands = tuple(command(data, i, "ListNumber", "numbered") for i in (0, 1, 3))
    changed = api().export_formats(data, commands)
    assert changed == api().export_formats(data, tuple(reversed(commands)))
    blocks = project_docx(changed).blocks
    assert blocks[0].numbering_id == blocks[1].numbering_id
    assert blocks[3].numbering_id != blocks[1].numbering_id
    assert blocks[2].numbering_id is None
    assert all(blocks[i].numbering_level == "0" for i in (0, 1, 3))
    assert [b.text for b in blocks] == [b.text for b in project_docx(data).blocks]
    continued = api().export_formats(
        changed, (command(changed, 2, "ListNumber", "numbered", blocks[0].numbering_id),)
    )
    assert project_docx(continued).blocks[2].numbering_id == blocks[0].numbering_id
    assert parts(continued)["word/numbering.xml"] == parts(changed)["word/numbering.xml"]
    same = command(changed, 0, "ListNumber", "numbered", blocks[0].numbering_id)
    assert api().export_formats(changed, (same,)) == changed
    numbering = ET.fromstring(parts(changed)["word/numbering.xml"])
    ids = [n.get(f"{{{W}}}numId") for n in numbering.findall("w:num", NS)]
    assert len(ids) == len(set(ids))
    for num_id in (blocks[0].numbering_id, blocks[3].numbering_id):
        num = numbering.find(f"w:num[@w:numId='{num_id}']", NS)
        aid = num.find("w:abstractNumId", NS).get(f"{{{W}}}val")
        lvl = numbering.find(f"w:abstractNum[@w:abstractNumId='{aid}']/w:lvl", NS)
        assert lvl.find("w:start", NS).get(f"{{{W}}}val") == "1"
        assert lvl.find("w:numFmt", NS).get(f"{{{W}}}val") == "decimal"


def test_bullet_and_removing_list_keep_other_definitions_unchanged():
    data = raw("bullet", "body")
    original_numbering = parts(data)["word/numbering.xml"]
    continued = api().export_formats(data, (command(data, 1, "ListBullet", "bullet", "1"),))
    assert parts(continued)["word/numbering.xml"] == original_numbering
    assert project_docx(continued).blocks[1].numbering_id == "1"
    removed = api().export_formats(continued, (command(continued, 0), command(continued, 1)))
    assert all(
        p.numbering_id is None and p.style_id == "Normal" for p in project_docx(removed).blocks
    )
    assert parts(removed)["word/numbering.xml"] == original_numbering


def test_new_numbering_preserves_old_children_and_correct_schema_order():
    data = raw("numbered", "body", "body")
    numbering = parts(data)["word/numbering.xml"]
    changed = api().export_formats(data, (command(data, 1, "ListBullet", "bullet"),))
    after = parts(changed)["word/numbering.xml"]
    old = ET.fromstring(numbering)
    new = ET.fromstring(after)
    serialized = [ET.tostring(n) for n in new]
    assert all(ET.tostring(n) in serialized for n in old)
    children = [n.tag.rsplit("}", 1)[-1] for n in new]
    assert max(i for i, t in enumerate(children) if t == "abstractNum") < min(
        i for i, t in enumerate(children) if t == "num"
    )
    for n in old:
        # Every old definition survives as raw XML too, including formatting.
        tag = n.tag.rsplit("}", 1)[-1]
        identity = n.get(f"{{{W}}}{'abstractNumId' if tag == 'abstractNum' else 'numId'}")
        attribute = "abstractNumId" if tag == "abstractNum" else "numId"
        marker = f'<w:{tag} w:{attribute}="{identity}">'.encode()
        start = numbering.index(marker)
        end = numbering.index(f"</w:{tag}>".encode(), start) + len(f"</w:{tag}>")
        assert numbering[start:end] in after


@pytest.mark.parametrize("which", ["pPr", "p"])
def test_self_closing_containers_are_expanded_safely(which):
    data = create_docx()
    main = parts(data)["word/document.xml"]
    begin = main.index(b"<w:p>")
    end = main.index(b"</w:p>", begin) + len(b"</w:p>")
    replacement = (
        b'<w:p custom="kept"><w:pPr/></w:p>' if which == "pPr" else b'<w:p custom="kept"/>'
    )
    data = replace_parts(data, {"word/document.xml": main[:begin] + replacement + main[end:]})
    changed = api().export_formats(data, (command(data, style="Heading1"),))
    assert project_docx(changed).blocks[0].style_id == "Heading1"
    assert b'custom="kept"' in parts(changed)["word/document.xml"]
    assert project_docx(changed).blocks[0].text == ""


@pytest.mark.parametrize("style", ["Missing", "ListBulletX"])
def test_unknown_style_is_not_silently_created(style):
    data = raw()
    rejects(lambda: api().export_formats(data, (command(data, style=style),)), "unsupported_format")


def test_character_style_and_ambiguous_style_rejected():
    data = raw()
    styles = parts(data)["word/styles.xml"]
    for payload in (
        styles.replace(
            b'w:type="paragraph" w:styleId="Heading1"', b'w:type="character" w:styleId="Heading1"'
        ),
        styles.replace(
            b"</w:styles>", b'<w:style w:type="paragraph" w:styleId="Heading1"/></w:styles>'
        ),
    ):
        changed = replace_parts(data, {"word/styles.xml": payload})
        rejects(
            lambda: api().export_formats(changed, (command(changed, style="Heading1"),)),
            "unsupported_format",
        )


@pytest.mark.parametrize(
    "kind,identity", [("numbered", "1"), ("bullet", "999"), ("numbered", "999")]
)
def test_existing_list_must_exist_and_match_its_kind(kind, identity):
    data = raw()
    rejects(
        lambda: api().export_formats(data, (command(data, kind=kind, identity=identity),)),
        "unsupported_format",
    )


def test_atomic_duplicate_mismatch_and_stale_commands():
    data = raw()
    value = command(data, style="Heading1")
    rejects(lambda: api().export_formats(data, (value, value)), "conflicting_formats")
    bad = api().ParagraphFormat(project_docx(data).blocks[1].anchor, "SYNTHETIC_PRIVATE", "Normal")
    rejects(lambda: api().export_formats(data, (value, bad)), "text_mismatch")
    changed = api().export_formats(data, (value,))
    rejects(lambda: api().export_formats(changed, (command(data),)), "stale_source")
    assert project_docx(data).blocks[0].style_id == "Normal"


def test_dto_limits_and_invalid_frozen_bypass():
    data = raw()
    value = api().ParagraphFormat(project_docx(data).blocks[0].anchor, "SYNTHETIC_PRIVATE")
    assert "SYNTHETIC_PRIVATE" not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.style_id = "other"
    for field, content in (
        ("style_id", 1),
        ("style_id", "x\x00"),
        ("style_id", "x\n"),
        ("list_kind", "ordered"),
        ("list_id", "0"),
        ("list_id", "01"),
        ("list_id", "2147483648"),
        ("anchor", None),
        ("expected_text", None),
    ):
        candidate = command(data)
        object.__setattr__(candidate, field, content)
        rejects(lambda: api().export_formats(data, (candidate,)))
    rejects(lambda: api().export_formats(data, []))
    rejects(lambda: api().export_formats(data, (object(),)))
    limits = api().FormatLimits(max_formats=1)
    rejects(
        lambda: api().export_formats(data, (command(data), command(data, 1)), format_limits=limits),
        "format_limit_exceeded",
    )
    rejects(
        lambda: api().export_formats(
            data, (command(data),), format_limits=api().FormatLimits(max_aux_nodes=1)
        ),
        "format_limit_exceeded",
    )
    for field in ("max_formats", "max_aux_nodes", "max_aux_depth"):
        limits = api().FormatLimits()
        object.__setattr__(limits, field, True)
        rejects(lambda: api().export_formats(data, (), format_limits=limits))
    with pytest.raises(DocxError):
        api().export_formats(data, (), limits=DocxLimits(max_archive_bytes=1))


def test_noop_protected_source_and_actual_change_refused():
    data = raw()
    settings = parts(data)["word/settings.xml"]
    data = replace_parts(
        data,
        {
            "word/settings.xml": settings.replace(
                b"<w:compat>", b"<w:documentProtection/><w:compat>"
            )
        },
    )
    assert api().export_formats(data, (command(data),)) == data
    rejects(
        lambda: api().export_formats(data, (command(data, style="Heading1"),)), "unsupported_format"
    )


def test_span_anchor_is_not_a_paragraph_anchor():
    data = raw()
    p = project_docx(data).blocks[0]
    value = api().ParagraphFormat(p.spans[0].anchor, p.text, "Heading1")
    rejects(lambda: api().export_formats(data, (value,)), "invalid_anchor")
    value = api().ParagraphFormat(
        SourceAnchor(p.anchor.source_sha256, "other.xml", p.anchor.path), p.text
    )
    rejects(lambda: api().export_formats(data, (value,)), "invalid_anchor")


def test_import_and_operations_are_inert():
    script = """
import importlib,builtins,io,os,socket,subprocess,logging
from pathlib import Path
from ara.docx_package.creation import create_docx
from ara.docx_package.projection import project_docx
raw=create_docx(); p=project_docx(raw).blocks[0]
def forbidden(*args,**kwargs):raise AssertionError("External I/O")
for obj,name in ((builtins,"open"),(io,"open"),(os,"getenv"),(socket,"socket"),
                 (subprocess,"Popen"),(Path,"read_bytes"),(Path,"write_bytes"),
                 (logging.Logger,"_log")):
    setattr(obj,name,forbidden)
m=importlib.import_module("ara.docx_package.formatting")
result=m.export_formats(raw,(m.ParagraphFormat(p.anchor,p.text,"Heading1","numbered"),))
assert project_docx(result).blocks[0].style_id=="Heading1"
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
