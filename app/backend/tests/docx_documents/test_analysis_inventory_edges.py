"""Additional inventory edges; no source content, remote reads or DB writes."""

from hashlib import sha256
from uuid import UUID

import pytest
from docx_package_fixtures import build_package, minimal_parts
from docx_projection_fixtures import package, paragraph
from test_docx_analysis_inventory import MARKER, inspect

from ara.docx_analysis import (
    InventoryError,
    InventoryLimits,
    build_snapshot,
    inventory_docx,
)
from ara.docx_package import DocxError


def test_package_metadata_names_and_raw_metadata_never_leak_through_repr():
    raw = package(
        paragraph(MARKER),
        main_part="custom/" + MARKER + ".xml",
        extra_parts={MARKER + ".bin": b"opaque"},
        links=[
            {
                "Id": MARKER,
                "Type": "urn:" + MARKER,
                "Target": "https://invalid.example/" + MARKER,
                "TargetMode": "External",
            }
        ],
    )[0]
    result = inspect(raw)
    assert MARKER not in repr(result)
    assert all(MARKER not in repr(p) for p in result.parts)
    assert all(MARKER not in repr(r) for r in result.relationships)


def test_mutated_and_subclassed_limits_are_revalidated():
    raw = package(paragraph("clean"))[0]
    limits = InventoryLimits()
    object.__setattr__(limits, "max_parts", True)

    class ChildLimits(InventoryLimits):
        pass

    for invalid in (limits, ChildLimits()):
        with pytest.raises(InventoryError) as caught:
            inspect(raw, limits=invalid)
        assert caught.value.code == "invalid_input"


def test_case_variant_content_types_name_remains_metadata():
    parts = minimal_parts()
    parts["[CONTENT_TYPES].xml"] = parts.pop("[Content_Types].xml")
    result = inspect(build_package(parts))
    entry = next(p for p in result.parts if p.content_type is None)
    assert entry.name == "[CONTENT_TYPES].xml"
    assert (entry.category, entry.disposition) == ("package_metadata", "metadata")


def test_missing_internal_target_is_package_error_and_original_is_unchanged():
    raw = package(
        paragraph("clean"), links=[{"Id": "missing", "Type": "urn:test", "Target": "missing.xml"}]
    )[0]
    before = sha256(raw).hexdigest()
    with pytest.raises(DocxError) as caught:
        inventory_docx(raw, source_sha256=before)
    assert caught.value.code == "invalid_package"
    assert sha256(raw).hexdigest() == before


def test_inventory_does_not_execute_final_revision_policy_or_mutate_a1():
    raw = package(
        "<w:p><w:ins><w:r><w:t>added</w:t></w:r></w:ins>"
        "<w:del><w:r><w:delText>removed</w:delText></w:r></w:del></w:p>"
    )[0]
    snapshot = build_snapshot(
        raw, document_id=UUID(int=1), storage_revision=1, source_sha256=sha256(raw).hexdigest()
    )
    inventory = inspect(raw)
    assert inventory.policy.revisions == "final"
    assert snapshot.analysis_text == "" and snapshot.complete is False
    assert (
        build_snapshot(
            raw, document_id=UUID(int=1), storage_revision=1, source_sha256=sha256(raw).hexdigest()
        )
        == snapshot
    )
