"""Frozen D03-17A2a metadata inventory and agreed Word policy acceptance."""

import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pytest
from docx_projection_fixtures import package, paragraph

WORD_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml."
MARKER = "SYNTHETIC_PRIVATE_INVENTORY_17A2"


def api():
    return import_module("ara.docx_analysis")


def inspect(raw, **kwargs):
    return api().inventory_docx(raw, source_sha256=sha256(raw).hexdigest(), **kwargs)


def error(code, operation):
    with pytest.raises(api().InventoryError) as caught:
        operation()
    assert caught.value.code == code
    assert MARKER not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize("strict", [False, True])
def test_inventory_all_parts_and_links_without_target_urls(strict):
    raw, _ = package(
        paragraph(MARKER),
        main_part="custom/Requirements.XML",
        strict=strict,
        extra_parts={"orphan.xml": b"<story/>", "private.bin": b"synthetic data"},
        extra_types={"orphan.xml": WORD_TYPE + "header+xml"},
        links=[
            {
                "Id": "rExternal",
                "Type": "urn:unknown",
                "Target": "https://invalid.example/" + MARKER,
                "TargetMode": "External",
            },
            {
                "Id": "rFile",
                "Type": "urn:unknown",
                "Target": "file:///" + MARKER,
                "TargetMode": "External",
            },
            {"Id": "rInternal", "Type": "urn:unknown", "Target": "../orphan.xml"},
        ],
    )
    inventory = inspect(raw)
    original = import_module("ara.docx_package").open_docx(raw)
    assert inspect(raw) == inventory
    assert inventory.source_sha256 == sha256(raw).hexdigest()
    assert inventory.size_bytes == len(raw) and inventory.main_part == "custom/Requirements.XML"
    assert [p.name for p in inventory.parts] == [p.name for p in original.entries]
    assert [(p.name, p.content_type, p.size_bytes, p.sha256) for p in inventory.parts] == [
        (p.name, p.content_type, p.size_bytes, p.sha256) for p in original.entries
    ]
    main = next(p for p in inventory.parts if p.name == inventory.main_part)
    assert (main.category, main.disposition) == ("main_body", "requires_reader")
    links = inventory.relationships
    assert [(r.source_part, r.relationship_id) for r in links] == [
        (r.source_part, r.relationship_id) for r in original.relationships
    ]
    assert all(not hasattr(r, "target") for r in links)
    assert all(r.resolved_part is None for r in links if r.target_mode == "External")
    assert next(r for r in links if r.relationship_id == "rInternal").resolved_part == "orphan.xml"
    assert [p.category for p in inventory.parts if p.name == "orphan.xml"] == ["header"]
    assert MARKER not in repr(inventory) + repr(links)
    assert not hasattr(inventory, "complete")
    assert not {"source", "data", "_original", "projection"} & {f.name for f in fields(inventory)}


@pytest.mark.parametrize(
    "mime,category,disposition",
    [
        *[
            (WORD_TYPE + value + "+xml", value, "requires_reader")
            for value in ("header", "footer", "footnotes", "endnotes")
        ],
        (WORD_TYPE + "document.glossary+xml", "glossary", "requires_reader"),
        (WORD_TYPE + "comments+xml", "comments", "preserve_excluded"),
        *[
            (WORD_TYPE + value + "+xml", "auxiliary", "metadata")
            for value in ("styles", "numbering", "settings", "webSettings", "fontTable")
        ],
        ("application/vnd.openxmlformats-officedocument.theme+xml", "auxiliary", "metadata"),
        ("application/vnd.openxmlformats-package.core-properties+xml", "auxiliary", "metadata"),
        ("application/vnd.openxmlformats-package.custom-properties+xml", "auxiliary", "metadata"),
        (
            "application/vnd.openxmlformats-officedocument.extended-properties+xml",
            "auxiliary",
            "metadata",
        ),
        *[
            (value, "image", "requires_media_accounting")
            for value in (
                "image/png",
                "image/jpeg",
                "image/gif",
                "image/bmp",
                "image/tiff",
                "image/x-emf",
                "image/x-wmf",
                "image/svg+xml",
            )
        ],
        ("application/xml", "unknown", "requires_reader"),
        (
            "application/vnd.openxmlformats-officedocument.drawingml.chart+xml",
            "unknown",
            "requires_reader",
        ),
        (WORD_TYPE + "header+xml;version=1", "unknown", "requires_reader"),
        ((WORD_TYPE + "header+xml").upper(), "unknown", "requires_reader"),
        ("application/octet-stream", "unknown", "requires_reader"),
    ],
)
def test_exact_mime_classification_not_filename(mime, category, disposition):
    raw, _ = package(
        paragraph("clean"),
        extra_parts={"misleading/header1.xml": b"<story/>"},
        extra_types={"misleading/header1.xml": mime},
    )
    entry = next(p for p in inspect(raw).parts if p.name == "misleading/header1.xml")
    assert (entry.category, entry.disposition) == (category, disposition)


def test_policy_is_fixed_and_inventory_does_not_relax_a1_coverage():
    raw, _ = package(
        paragraph("clean"),
        extra_parts={"word/comments.xml": b"<story/>"},
        extra_types={"word/comments.xml": WORD_TYPE + "comments+xml"},
    )
    inventory = inspect(raw)
    policy = inventory.policy
    assert type(policy) is api().AnalysisPolicy
    assert (policy.version, policy.revisions, policy.comments) == (
        "docx-analysis-policy/final-no-comments-v1",
        "final",
        "preserve_exclude",
    )
    with pytest.raises(FrozenInstanceError):
        policy.comments = "include"
    with pytest.raises(TypeError):
        api().AnalysisPolicy(revisions="original")
    from uuid import UUID

    snapshot = api().build_snapshot(
        raw, document_id=UUID(int=1), storage_revision=1, source_sha256=sha256(raw).hexdigest()
    )
    assert not snapshot.complete
    assert not hasattr(inventory, "__dict__")
    assert type(inventory.parts) is type(inventory.relationships) is tuple
    metadata = [p for p in inventory.parts if p.category == "package_metadata"]
    assert {p.name for p in metadata} == {"[Content_Types].xml", "_rels/.rels"}


@pytest.mark.parametrize("field", ["max_parts", "max_relationships"])
def test_limits_inclusive_and_strict(field):
    raw, _ = package(paragraph("clean"))
    count = 3 if field == "max_parts" else 1
    assert inspect(raw, limits=api().InventoryLimits(**{field: count})).parts
    if count > 1:
        error(
            "inventory_limit_exceeded",
            lambda: inspect(raw, limits=api().InventoryLimits(**{field: count - 1})),
        )
    else:
        larger = package(
            paragraph("clean"),
            links=[
                {
                    "Id": "external",
                    "Type": "urn:test",
                    "Target": "https://invalid.example/",
                    "TargetMode": "External",
                }
            ],
        )[0]
        error(
            "inventory_limit_exceeded",
            lambda: inspect(larger, limits=api().InventoryLimits(max_relationships=1)),
        )
    for invalid in (True, False, 0, -1, 1.2, "1"):
        error("invalid_input", lambda: api().InventoryLimits(**{field: invalid}))


def test_strict_input_hash_and_package_limits():
    raw = package(paragraph(MARKER))[0]
    for value in (None, bytearray(raw), memoryview(raw), "data"):
        error("invalid_input", lambda: api().inventory_docx(value, source_sha256="0" * 64))
    for value in (None, "", "A" * 64, True):
        error("invalid_input", lambda: api().inventory_docx(raw, source_sha256=value))
    error("source_mismatch", lambda: api().inventory_docx(raw, source_sha256="0" * 64))
    error("invalid_input", lambda: inspect(raw, limits={}))
    package_api = import_module("ara.docx_package")
    with pytest.raises(package_api.DocxError):
        inspect(b"bad zip")
    with pytest.raises(package_api.DocxError) as caught:
        inspect(b"x" * (33554432 + 1))
    assert caught.value.code == "package_limit_exceeded"


def test_fresh_process_inert_import_and_inventory():
    raw = package(paragraph(MARKER))[0]
    script = """
import builtins,io,os,socket,sys
from pathlib import Path
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*args,**kwargs):
    raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=forbidden
from ara.docx_analysis import inventory_docx
result=inventory_docx(data,source_sha256=sha256(data).hexdigest())
assert len(result.parts)==3
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    child = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=30,
    )
    assert child.returncode == 0, child.stderr.decode()
    assert child.stdout == b""
