"""Frozen D03-11: anchored paragraph operations preserve untouched DOCX bytes."""

import importlib
import io
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx_editing_fixtures import zip_parts
from docx_projection_fixtures import package, paragraph

from ara.docx_package import DocxError, DocxLimits
from ara.docx_package.creation import NewParagraph, create_docx
from ara.docx_package.projection import (
    ProjectionError,
    ProjectionLimits,
    SourceAnchor,
    project_docx,
)

ROOT = Path(__file__).resolve().parents[2]
MAIN = "word/document.xml"


def api():
    return importlib.import_module("ara.docx_package.structure")


def paragraphs(data):
    return [b for b in project_docx(data).blocks if b.kind == "paragraph"]


def source(*texts):
    return create_docx(tuple(NewParagraph(t) for t in (texts or ("one", "two", "three"))))


def ins(data, *texts, index=0, position="after"):
    p = paragraphs(data)[index]
    return api().InsertParagraph(p.anchor, p.text, tuple(texts or ("inserted",)), position)


def delete(data, index=0):
    p = paragraphs(data)[index]
    return api().DeleteParagraph(p.anchor, p.text)


def rejects(call, code="invalid_input"):
    with pytest.raises(api().StructureError) as caught:
        call()
    assert caught.value.code == code
    assert str(caught.value) == caught.value.message and caught.value.message
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize(
    "position,expected",
    [("before", ["A", "", "one", "two", "three"]), ("after", ["one", "A", "", "two", "three"])],
)
def test_insert_many_keeps_order_and_original_paragraphs(position, expected):
    data = source()
    result = api().export_structure(data, (ins(data, "A", "", position=position),))
    assert [p.text for p in paragraphs(result)] == expected
    assert all(
        p.anchor.source_sha256 == project_docx(result).source.sha256 for p in paragraphs(result)
    )
    assert project_docx(result).source.sha256 != project_docx(data).source.sha256
    assert zip_parts(data)["word/styles.xml"] == zip_parts(result)["word/styles.xml"]


def test_literal_text_empty_tab_lf_unicode_and_escaping():
    data = source()
    text = '  <реле> & "x" 😀 e\u0301\t\n\n end  '
    result = api().export_structure(data, (ins(data, text, ""),))
    assert [p.text for p in paragraphs(result)] == ["one", text, "", "two", "three"]
    assert paragraphs(result)[2].spans[0].kind == "text"
    assert not project_docx(result).has_unprojected_content


def test_delete_and_original_anchor_safety():
    data = source()
    result = api().export_structure(data, (delete(data, 1),))
    assert [p.text for p in paragraphs(result)] == ["one", "three"]
    rejects(lambda: api().export_structure(result, (delete(data),)), "stale_source")
    changed = api().export_structure(result, (ins(result, "new"),))
    assert [p.text for p in paragraphs(changed)] == ["one", "new", "three"]


def test_last_paragraph_and_batch_all_delete_refused():
    data = source("only")
    rejects(lambda: api().export_structure(data, (delete(data),)), "unsupported_structure")
    data = source()
    rejects(
        lambda: api().export_structure(data, tuple(delete(data, i) for i in range(3))),
        "unsupported_structure",
    )


def test_independent_batch_is_atomic_and_order_invariant():
    data = source()
    commands = (ins(data, "A", position="before"), delete(data, 2))
    first = api().export_structure(data, commands)
    assert first == api().export_structure(data, tuple(reversed(commands)))
    assert [p.text for p in paragraphs(first)] == ["A", "one", "two"]
    bad = api().DeleteParagraph(paragraphs(data)[1].anchor, "SYNTHETIC_PRIVATE_wrong")
    rejects(lambda: api().export_structure(data, (commands[0], bad)), "text_mismatch")
    assert [p.text for p in paragraphs(data)] == ["one", "two", "three"]


@pytest.mark.parametrize("kind", ["same", "same_boundary", "delete_boundary"])
def test_conflicting_commands_rejected(kind):
    data = source()
    commands = {
        "same": (ins(data), delete(data)),
        "same_boundary": (ins(data), ins(data, index=1, position="before")),
        "delete_boundary": (delete(data), ins(data, index=1, position="before")),
    }[kind]
    rejects(lambda: api().export_structure(data, commands), "conflicting_commands")


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be"])
def test_encoding_namespace_custom_main_and_exact_xml_outside_ranges(strict, encoding):
    one, two = paragraph("one"), paragraph("two")
    data, original = package(
        one + two,
        strict=strict,
        encoding={"utf-16-le": "utf-16le", "utf-16-be": "utf-16be"}.get(encoding, encoding),
        main_part="custom/Requirements.XML",
    )
    result = api().export_structure(data, (ins(data, "Реле 😀"),))
    main = "custom/Requirements.XML"
    actual = zip_parts(result)[main]
    end = original.index(
        "</w:p>".encode(
            encoding.replace("utf-16", "utf-16-le") if encoding == "utf-16" else encoding
        )
    )
    # Keep lexical boundaries; this fixture runtime emits little-endian UTF-16 with BOM.
    codec = "utf-16-le" if encoding == "utf-16" else encoding
    end += len("</w:p>".encode(codec))
    assert actual[:end] == original[:end]
    assert actual.endswith(original[end:])
    assert [p.text for p in paragraphs(result)] == ["one", "Реле 😀", "two"]
    deleted = api().export_structure(data, (delete(data),))
    assert zip_parts(deleted)[main] == original.replace(one.encode(codec), b"", 1)


def test_local_namespace_and_self_closing_target_are_safe():
    body = (
        '<q:p xmlns:q="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
        + paragraph("keep")
    )
    data, original = package(body)
    result = api().export_structure(data, (ins(data, "new"),))
    assert [p.text for p in paragraphs(result)] == ["", "new", "keep"]
    assert body.split("/>")[0].encode() + b"/>" in zip_parts(result)[MAIN]
    deleted = api().export_structure(data, (delete(data),))
    assert zip_parts(deleted)[MAIN] == original.replace(
        body.split("/>")[0].encode() + b"/>", b"", 1
    )


def test_zip_parts_metadata_comments_and_directories_preserved():
    from docx_editing_fixtures import raw_package

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><!--outside--><?keep yes?>"
        + paragraph("one")
        + paragraph("two")
        + "</w:body></w:document>"
    ).encode()
    comment = b"legal PK\x05\x06 trailer"
    data = raw_package(
        xml, extra_parts={"media/payload.bin": b"opaque"}, directories=("media/",), comment=comment
    )
    result = api().export_structure(data, (ins(data),))
    before, after = zip_parts(data, comment=comment), zip_parts(result, comment=comment)
    assert set(before) == set(after)
    assert all(before[n] == after[n] for n in before if n != MAIN)
    assert b"<!--outside--><?keep yes?>" in after[MAIN]
    with (
        ZipFile(io.BytesIO(data[: -len(comment)])) as a,
        ZipFile(io.BytesIO(result[: -len(comment)])) as b,
    ):
        assert a.namelist() == b.namelist()
        for x, y in zip(a.infolist(), b.infolist(), strict=True):
            assert (
                x.filename,
                x.date_time,
                x.compress_type,
                x.create_system,
                x.external_attr,
                x.internal_attr,
                x.comment,
                x.extra,
            ) == (
                y.filename,
                y.date_time,
                y.compress_type,
                y.create_system,
                y.external_attr,
                y.internal_attr,
                y.comment,
                y.extra,
            )
    assert result.endswith(comment)


@pytest.mark.parametrize(
    "marker",
    [
        '<w:bookmarkStart w:id="1" w:name="x"/>',
        '<w:commentRangeStart w:id="1"/>',
        '<w:permStart w:id="1"/>',
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>',
        "<w:r><w:instrText>PAGE</w:instrText></w:r>",
        "<w:ins><w:r><w:t>revision</w:t></w:r></w:ins>",
    ],
)
def test_global_ranges_fields_and_revisions_are_not_silently_changed(marker):
    data, _ = package(paragraph("safe") + f"<w:p>{marker}</w:p>")
    view = project_docx(data)
    # Complex fields deliberately make the existing projection opaque. Address
    # the fixture's known first p without requiring a projected text paragraph.
    anchor = SourceAnchor(view.source.sha256, view.source.main_part, view.body_anchor.path + (0,))
    command = api().InsertParagraph(anchor, "safe")
    rejects(lambda: api().export_structure(data, (command,)), "unsupported_structure")
    assert api().export_structure(data, ()) == data


@pytest.mark.parametrize(
    "inner",
    [
        "<!--keep-->",
        "<?keep yes?>",
        "<w:drawing/>",
        '<w:hyperlink w:anchor="x"><w:r><w:t>link</w:t></w:r></w:hyperlink>',
    ],
)
def test_target_opaque_or_annotations_rejected(inner):
    data, _ = package(f"<w:p><w:r><w:t>safe</w:t></w:r>{inner}</w:p>" + paragraph("keep"))
    rejects(lambda: api().export_structure(data, (ins(data),)), "unsupported_structure")
    rejects(lambda: api().export_structure(data, (delete(data),)), "unsupported_structure")


def test_section_boundary_and_nested_cell_are_not_accepted_as_body_targets():
    data, _ = package(
        paragraph("section", properties="<w:pPr><w:sectPr/></w:pPr>") + paragraph("keep")
    )
    rejects(lambda: api().export_structure(data, (delete(data),)), "unsupported_structure")
    data, _ = package(
        "<w:tbl><w:tr><w:tc>" + paragraph("cell") + "</w:tc></w:tr></w:tbl>" + paragraph("body")
    )
    p = project_docx(data).blocks[0].rows[0].cells[0].blocks[0]
    rejects(
        lambda: api().export_structure(data, (api().DeleteParagraph(p.anchor, p.text),)),
        "invalid_anchor",
    )


@pytest.mark.parametrize(
    "setting", ['<w:documentProtection w:enforcement="false"/>', "<w:trackRevisions/>"]
)
def test_settings_protection_gate_and_exact_noop(setting):
    uri = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    data, _ = package(
        paragraph("one") + paragraph("two"),
        extra_parts={
            "word/settings.xml": f'<w:settings xmlns:w="{uri}">{setting}</w:settings>'.encode()
        },
        extra_types={
            "word/settings.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
            )
        },
    )
    rejects(lambda: api().export_structure(data, (ins(data),)), "unsupported_structure")
    assert api().export_structure(data, ()) == data


def test_signature_gate():
    data, _ = package(
        paragraph("one"),
        extra_parts={"_xmlsignatures/sig.xml": b"<signature/>"},
        extra_types={"_xmlsignatures/sig.xml": "application/xml"},
    )
    rejects(lambda: api().export_structure(data, (ins(data),)), "unsupported_structure")


def test_limits_and_strict_mutated_dtos():
    data = source()
    p = paragraphs(data)[0]
    module = api()
    command = module.InsertParagraph(p.anchor, "SYNTHETIC_PRIVATE")
    assert "SYNTHETIC_PRIVATE" not in repr(command)
    with pytest.raises(FrozenInstanceError):
        command.position = "before"
    for field, value in (
        ("anchor", None),
        ("expected_text", None),
        ("texts", []),
        ("texts", ()),
        ("texts", (1,)),
        ("position", "middle"),
    ):
        changed = ins(data)
        object.__setattr__(changed, field, value)
        rejects(lambda: module.export_structure(data, (changed,)))
    rejects(lambda: module.export_structure(data, []))
    rejects(lambda: module.export_structure(data, (object(),)))
    for key in ("max_commands", "max_new_paragraphs", "max_text_chars"):
        limits = module.StructureLimits()
        object.__setattr__(limits, key, True)
        rejects(lambda: module.export_structure(data, (), structure_limits=limits))
    limits = module.StructureLimits(1, 2, 2)
    assert module.export_structure(data, (ins(data, "😀", "&"),), structure_limits=limits)
    rejects(
        lambda: module.export_structure(data, (ins(data, "😀&x"),), structure_limits=limits),
        "structure_limit_exceeded",
    )
    rejects(
        lambda: module.export_structure(data, (ins(data, "", "", ""),), structure_limits=limits),
        "structure_limit_exceeded",
    )
    rejects(
        lambda: module.export_structure(
            data, (ins(data), delete(data, 2)), structure_limits=limits
        ),
        "structure_limit_exceeded",
    )


@pytest.mark.parametrize("text", ["\r", "\r\n", "\x00", "\x0b", "\ud800", "\ufffe"])
def test_bad_new_text_is_rejected(text):
    data = source()
    rejects(lambda: api().export_structure(data, (ins(data, text),)))


def test_invalid_anchor_and_package_projection_errors():
    data = source()
    p = paragraphs(data)[0]
    for anchor in (
        SourceAnchor(p.anchor.source_sha256, "other.xml", p.anchor.path),
        paragraphs(data)[0].spans[0].anchor,
    ):
        rejects(
            lambda: api().export_structure(data, (api().DeleteParagraph(anchor, p.text),)),
            "invalid_anchor",
        )
    anchor = SourceAnchor(p.anchor.source_sha256, p.anchor.part_name, (False, 0))
    rejects(lambda: api().export_structure(data, (api().DeleteParagraph(anchor, p.text),)))
    with pytest.raises(DocxError):
        api().export_structure(data, (), limits=DocxLimits(max_archive_bytes=1))
    with pytest.raises(ProjectionError):
        api().export_structure(data, (), projection_limits=ProjectionLimits(max_nodes=1))


def test_imports_and_operations_are_inert():
    script = """
import importlib, builtins, io, os, socket, subprocess, logging
from pathlib import Path
from ara.docx_package.creation import create_docx
from ara.docx_package.projection import project_docx
raw=create_docx(); p=project_docx(raw).blocks[0]
def forbidden(*args, **kwargs):
    raise AssertionError("External resource access")
for obj,name in ((builtins,"open"),(io,"open"),(os,"getenv"),(socket,"socket"),
                 (subprocess,"Popen"),(Path,"read_bytes"),(Path,"write_bytes"),
                 (logging.Logger,"_log")):
    setattr(obj,name,forbidden)
m=importlib.import_module("ara.docx_package.structure")
result=m.export_structure(raw,(m.InsertParagraph(p.anchor,p.text,("new",)),))
assert [p.text for p in project_docx(result).blocks]==["","new"]
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
