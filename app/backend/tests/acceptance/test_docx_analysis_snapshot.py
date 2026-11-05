"""Frozen D03-17A1 acceptance; only synthetic in-memory Word documents."""

import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict, fields, replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree as ET

import pytest
from docx_projection_fixtures import package, paragraph

DOC = UUID("12345678-1234-4234-9234-123456789abc")
MARKER = "SYNTHETIC_PRIVATE_17A1"


def api():
    return import_module("ara.docx_analysis")


def build(raw, **kwargs):
    return api().build_snapshot(
        raw,
        document_id=DOC,
        storage_revision=7,
        source_sha256=sha256(raw).hexdigest(),
        **kwargs,
    )


def digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def error(code, operation):
    with pytest.raises(api().SnapshotError) as caught:
        operation()
    assert caught.value.code == code
    assert MARKER not in str(caught.value)
    assert MARKER not in repr(caught.value)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_exact_text_identity_manifest_and_xml_anchors(strict, encoding):
    body = paragraph("Hi", properties='<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>')
    body += paragraph(
        "  1. реле  ", properties='<w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr>'
    )
    body += '<w:p><w:r><w:t>A😀é</w:t><w:t/></w:r><w:hyperlink w:anchor="local">'
    body += "<w:r><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t></w:r></w:hyperlink></w:p>"
    raw, xml = package(body, strict=strict, encoding=encoding, main_part="custom/doc.xml")
    snap = build(raw)
    assert snap == build(raw)
    assert snap.document_id == DOC and snap.storage_revision == 7
    assert snap.extractor_version == "docx-analysis/main-body-v1"
    assert snap.main_part == "custom/doc.xml"
    assert snap.complete is True and snap.has_unprojected_content is False
    texts = ["Hi", "  1. реле  ", "A😀é\tB\nC"]
    assert [f.text for f in snap.fragments] == texts
    assert snap.analysis_text == "\n\n".join(texts)
    assert snap.text_sha256 == sha256(snap.analysis_text.encode()).hexdigest()
    root = ET.fromstring(xml)
    for fragment in snap.fragments:
        assert snap.analysis_text[fragment.analysis_start : fragment.analysis_end] == fragment.text
        anchor = fragment.paragraph_anchor
        assert fragment.ancestry == (snap.body_anchor,)
        assert anchor.source_sha256 == sha256(raw).hexdigest()
        assert fragment.fragment_id == "f-" + digest(
            {
                "domain": "docx-analysis-fragment/1",
                "source_sha256": anchor.source_sha256,
                "part_name": anchor.part_name,
                "path": list(anchor.path),
            }
        )
        position = 0
        for segment in fragment.segments:
            assert segment.start == position < segment.end
            position = segment.end
            node = root
            for index in segment.anchor.path:
                node = node[index]
            assert node.tag.rsplit("}", 1)[-1] in ("t", "tab", "br", "cr")
        assert position == len(fragment.text)
    manifest = asdict(snap)
    manifest.pop("snapshot_sha256")
    manifest["document_id"] = str(DOC)
    manifest["storage_revision"] = "7"
    assert snap.snapshot_sha256 == digest(manifest)
    assert set(manifest) == {
        "document_id",
        "storage_revision",
        "source_sha256",
        "extractor_version",
        "main_part",
        "body_anchor",
        "fragments",
        "analysis_text",
        "coverage",
        "has_unprojected_content",
        "complete",
        "text_sha256",
    }
    changed = api().build_snapshot(
        raw, document_id=DOC, storage_revision=8, source_sha256=sha256(raw).hexdigest()
    )
    assert changed.snapshot_sha256 != snap.snapshot_sha256
    assert changed.fragments == snap.fragments


def test_nested_physical_cells_duplicates_and_ancestry():
    inner = "<w:tbl><w:tr><w:tc>" + paragraph("inside") + "</w:tc></w:tr></w:tbl>"
    body = '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/>'
    body += '<w:vMerge w:val="restart"/></w:tcPr>' + paragraph("same") + inner
    body += "</w:tc><w:tc>" + paragraph("same") + "</w:tc></w:tr></w:tbl>"
    snap = build(package(body)[0])
    assert [f.text for f in snap.fragments] == ["same", "inside", "same"]
    assert len({f.fragment_id for f in snap.fragments}) == 3
    assert [len(f.ancestry) for f in snap.fragments] == [4, 7, 4]
    assert [a.path for a in snap.fragments[1].ancestry] == [
        (0,),
        (0, 0),
        (0, 0, 0),
        (0, 0, 0, 0),
        (0, 0, 0, 0, 2),
        (0, 0, 0, 0, 2, 0),
        (0, 0, 0, 0, 2, 0, 0),
    ]


def test_mapping_across_runs_tabs_breaks_reconstructs_exact_quote():
    raw, _ = package(
        "<w:p><w:r><w:t>A😀é</w:t></w:r><w:r><w:tab/><w:t>BC</w:t><w:br/><w:t>D</w:t></w:r></w:p>"
    )
    snap = build(raw)
    fragment = snap.fragments[0]
    quote = fragment.text[1:8]
    mapped = api().map_span(snap, fragment_id=fragment.fragment_id, start=1, end=8, quote=quote)
    projection = import_module("ara.docx_package.projection").project_docx(raw)
    original = {s.anchor: s for s in projection.blocks[0].spans}
    assert "".join(original[s.anchor].text[s.start : s.end] for s in mapped.slices) == quote
    assert [s.kind for s in mapped.slices] == ["text", "tab", "text", "break"]
    assert mapped.paragraph_anchor == fragment.paragraph_anchor
    assert (mapped.start, mapped.end) == (1, 8)


@pytest.mark.parametrize(
    "start,end,quote",
    [
        (0, 0, ""),
        (-1, 1, "A"),
        (True, 2, "😀"),
        (0, False, ""),
        (0, 100, MARKER),
        (2, 3, "😀"),
        (0, 1, "wrong"),
        (0.0, 1, "A"),
        (0, 1, None),
    ],
)
def test_bad_offsets_or_quotes_are_not_repaired(start, end, quote):
    snap = build(package(paragraph("A😀BC"))[0])
    error(
        "invalid_span",
        lambda: api().map_span(
            snap, fragment_id=snap.fragments[0].fragment_id, start=start, end=end, quote=quote
        ),
    )


def test_unknown_fragment_and_duplicate_quote_not_guessed():
    snap = build(package(paragraph("same") + paragraph("same"))[0])
    error(
        "unknown_fragment",
        lambda: api().map_span(snap, fragment_id="missing", start=0, end=4, quote="same"),
    )
    mapped = api().map_span(
        snap, fragment_id=snap.fragments[1].fragment_id, start=0, end=4, quote="same"
    )
    assert mapped.paragraph_anchor == snap.fragments[1].paragraph_anchor


@pytest.mark.parametrize(
    "body",
    [
        "<w:p><w:r><w:t>left</w:t><w:drawing/><w:t>right</w:t></w:r></w:p>",
        '<w:p><w:ins w:id="1"><w:r><w:t>revision</w:t></w:r></w:ins></w:p>',
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/><w:t>field</w:t></w:r></w:p>',
        "<s:unknown/>" + paragraph("clean"),
    ],
)
def test_opaque_content_is_blocking_and_not_sent_as_clean_text(body):
    raw, _ = package(body)
    snap = build(raw)
    assert snap.complete is False
    assert any(c.status == "blocked" for c in snap.coverage)
    assert not any(word in snap.analysis_text for word in ("left", "right", "revision", "field"))
    assert raw == package(body)[0]


def test_notice_stories_empty_and_literal_object_character():
    raw, _ = package(
        paragraph("\ufffc") + paragraph(" \t ") + "<w:p/>",
        extra_parts={"word/header1.xml": b"<story/>"},
        extra_types={
            "word/header1.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
            )
        },
    )
    snap = build(raw)
    assert [f.text for f in snap.fragments] == ["\ufffc"]
    assert [c.status for c in snap.coverage[:3]] == ["included", "empty", "empty"]
    assert any(c.code == "notice:unprojected_story" for c in snap.coverage)
    assert not snap.complete
    empty = build(package("")[0])
    assert empty.complete and empty.fragments == () and empty.analysis_text == ""


@pytest.mark.parametrize(
    "name,value",
    [
        ("document_id", str(DOC)),
        ("storage_revision", True),
        ("storage_revision", 0),
        ("storage_revision", 2**63),
        ("source_sha256", "A" * 64),
        ("source_sha256", None),
        ("limits", {}),
    ],
)
def test_strict_input_identity(name, value):
    raw = package(paragraph(MARKER))[0]
    kwargs = dict(document_id=DOC, storage_revision=1, source_sha256=sha256(raw).hexdigest())
    kwargs[name] = value
    error("invalid_input", lambda: api().build_snapshot(raw, **kwargs))


def test_hash_mismatch_and_package_errors_are_safe():
    raw = package(paragraph(MARKER))[0]
    error(
        "source_mismatch",
        lambda: api().build_snapshot(
            raw, document_id=DOC, storage_revision=1, source_sha256="0" * 64
        ),
    )
    package_api = import_module("ara.docx_package")
    with pytest.raises(package_api.DocxError):
        build(b"not a zip")
    too_big = b"x" * (33554432 + 1)
    with pytest.raises(package_api.DocxError) as caught:
        build(too_big, limits=api().SnapshotLimits(max_text_characters=2**40))
    assert caught.value.code == "package_limit_exceeded"


@pytest.mark.parametrize(
    "name,limit",
    [
        ("max_fragments", 2),
        ("max_text_characters", 4),
        ("max_segments", 2),
        ("max_coverage_items", 2),
    ],
)
def test_inclusive_budgets_no_truncation(name, limit):
    raw = package(paragraph("A") + paragraph("B"))[0]
    assert len(build(raw, limits=api().SnapshotLimits(**{name: limit})).fragments) == 2
    error(
        "snapshot_limit_exceeded",
        lambda: build(raw, limits=api().SnapshotLimits(**{name: limit - 1})),
    )
    for bad in (True, 0, -1, 1.5):
        error("invalid_input", lambda: api().SnapshotLimits(**{name: bad}))


@pytest.mark.parametrize(
    "change",
    [
        {"analysis_text": MARKER},
        {"snapshot_sha256": "0" * 64},
        {"complete": False},
        {"text_sha256": "0" * 64},
        {"extractor_version": "unknown"},
        {"coverage": ()},
        {"source_sha256": "0" * 64},
        {"storage_revision": True},
    ],
)
def test_tampered_snapshot_is_refused(change):
    snap = build(package(paragraph("text"))[0])
    error(
        "invalid_snapshot",
        lambda: api().map_span(
            replace(snap, **change),
            fragment_id=snap.fragments[0].fragment_id,
            start=0,
            end=1,
            quote="t",
        ),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"text": MARKER},
        {"analysis_start": True},
        {"segments": ()},
        {"paragraph_anchor": None},
        {"fragment_id": "wrong"},
        {"ancestry": []},
    ],
)
def test_tampered_fragment_is_refused(change):
    snap = build(package(paragraph("text"))[0])
    broken = replace(snap, fragments=(replace(snap.fragments[0], **change),))
    error(
        "invalid_snapshot",
        lambda: api().map_span(
            broken, fragment_id=snap.fragments[0].fragment_id, start=0, end=1, quote="t"
        ),
    )


def test_immutable_graph_and_safe_repr():
    snap = build(package(paragraph(MARKER))[0])
    assert MARKER not in repr(snap)
    assert MARKER not in repr(snap.fragments[0])
    with pytest.raises(FrozenInstanceError):
        snap.complete = False
    assert not hasattr(snap, "__dict__")
    assert not any(f.name in ("source", "data", "_original", "projection") for f in fields(snap))
    assert type(snap.fragments) is type(snap.coverage) is tuple


def test_fresh_process_import_and_operations_are_inert():
    raw = package(paragraph(MARKER))[0]
    script = """
import builtins, io, os, socket, sys
from pathlib import Path
from uuid import UUID
from hashlib import sha256
data = sys.stdin.buffer.read()
def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected application I/O")
builtins.open = io.open = Path.open = forbidden
os.getenv = os._Environ.__getitem__ = forbidden
socket.socket = socket.create_connection = forbidden
from ara.docx_analysis import build_snapshot, map_span
s = build_snapshot(data, document_id=UUID("12345678-1234-4234-9234-123456789abc"),
                   storage_revision=1, source_sha256=sha256(data).hexdigest())
f = s.fragments[0]
map_span(s, fragment_id=f.fragment_id, start=0, end=1, quote=f.text[:1])
blocked = {"onnxruntime", "numpy", "aira_ml", "psycopg", "sqlalchemy", "fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    child_env = {"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")}
    child = subprocess.run(
        [sys.executable, "-c", script], input=raw, capture_output=True, env=child_env, timeout=30
    )
    assert child.returncode == 0, child.stderr.decode()
    assert child.stdout == b""


def test_notice_counts_towards_budget_and_projection_budget_is_unchanged():
    raw = package("<s:unknown/>" + paragraph("clean"))[0]
    snap = build(raw)
    limit = len(snap.coverage)
    assert build(raw, limits=api().SnapshotLimits(max_coverage_items=limit)) == snap
    error(
        "snapshot_limit_exceeded",
        lambda: build(raw, limits=api().SnapshotLimits(max_coverage_items=limit - 1)),
    )
    projection = import_module("ara.docx_package.projection")
    with pytest.raises(projection.ProjectionError) as caught:
        build(package("<w:p/>" * 100001)[0])
    assert caught.value.code == "projection_limit_exceeded"


@pytest.mark.parametrize("value", [None, "data", bytearray(b"data"), memoryview(b"data")])
def test_concrete_bytes_required(value):
    error(
        "invalid_input",
        lambda: api().build_snapshot(
            value, document_id=DOC, storage_revision=1, source_sha256="0" * 64
        ),
    )
