"""Frozen b1 acceptance: independent final strings and original XML addresses."""

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
PRIVATE = "SYNTHETIC_PRIVATE_FINAL_VIEW"


def api():
    return import_module("ara.docx_analysis.final_view")


def p(text, mark=None):
    properties = "" if mark is None else f'<w:pPr><w:rPr><w:{mark} w:id="1"/></w:rPr></w:pPr>'
    return paragraph(text, properties=properties)


def build(raw, **kwargs):
    return api().build_final_snapshot(
        raw, document_id=DOC, storage_revision=9, source_sha256=sha256(raw).hexdigest(), **kwargs
    )


def digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def rehash(snapshot):
    value = asdict(snapshot)
    value.pop("snapshot_sha256")
    value["document_id"] = str(snapshot.document_id)
    value["storage_revision"] = str(snapshot.storage_revision)
    return replace(snapshot, snapshot_sha256=digest(value))


def error(code, operation):
    with pytest.raises(api().FinalViewError) as caught:
        operation()
    assert caught.value.code == code
    assert PRIVATE not in repr(caught.value) + str(caught.value)


def resolve(root, anchor):
    for index in anchor.path:
        root = root[index]
    return root


def reconstruct(root, mapped):
    values = []
    for item in mapped.slices:
        node = resolve(root, item.anchor)
        name = node.tag.rsplit("}", 1)[-1]
        value = node.text or "" if name == "t" else "\t" if name == "tab" else "\n"
        values.append(value[item.start : item.end])
        assert node.tag.rsplit("}", 1)[-1] in ("t", "tab", "br", "cr")
    return "".join(values)


@pytest.mark.parametrize("strict,encoding", [(False, "utf-8"), (True, "utf-16")])
def test_revisions_exact_text_manifest_and_independent_ranges(strict, encoding):
    body = '<w:p><w:r><w:t xml:space="preserve"> A😀é</w:t><w:t/></w:r>'
    body += '<w:del w:id="1"><w:r><w:delText>old</w:delText></w:r>'
    body += '<w:ins w:id="2"><s:opaque/></w:ins></w:del>'
    body += '<w:ins w:id="3"><w:hyperlink w:anchor="local"><w:r><w:tab/>'
    body += "<w:t>new</w:t><w:br/><w:t>\ufffc</w:t></w:r></w:hyperlink></w:ins></w:p>"
    raw, xml = package(body, strict=strict, encoding=encoding, main_part="custom/Final.xml")
    snap = build(raw)
    assert snap == build(raw) and snap.complete
    assert snap.profile == "docx-analysis/final-main-v1"
    assert snap.policy_version == "docx-analysis-policy/final-no-comments-v1"
    assert snap.main_part == "custom/Final.xml"
    assert snap.analysis_text == " A😀é\tnew\n\ufffc"
    fragment = snap.fragments[0]
    assert fragment.text == snap.analysis_text
    assert len(fragment.paragraph_anchors) == 1 and fragment.joins == ()
    assert fragment.story_anchor == fragment.flow_anchor
    root = ET.fromstring(xml)
    for start in range(len(fragment.text)):
        for end in range(start + 1, len(fragment.text) + 1):
            quote = fragment.text[start:end]
            mapped = api().map_final_span(
                snap, fragment_id=fragment.fragment_id, start=start, end=end, quote=quote
            )
            assert reconstruct(root, mapped) == quote
    manifest = asdict(snap)
    manifest.pop("snapshot_sha256")
    manifest["document_id"], manifest["storage_revision"] = str(DOC), "9"
    assert snap.snapshot_sha256 == digest(manifest)
    assert snap.text_sha256 == sha256(snap.analysis_text.encode()).hexdigest()
    expected_id = {
        k: manifest["fragments"][0][k]
        for k in ("story_anchor", "flow_anchor", "paragraph_anchors", "joins")
    }
    expected_id.update(
        domain="docx-final-fragment/1",
        profile=snap.profile,
        policy_version=snap.policy_version,
        source_sha256=snap.source_sha256,
    )
    assert fragment.fragment_id == "lf-" + digest(expected_id)
    assert {f.name for f in fields(snap)} == {
        "document_id",
        "storage_revision",
        "source_sha256",
        "profile",
        "policy_version",
        "main_part",
        "fragments",
        "analysis_text",
        "coverage",
        "complete",
        "text_sha256",
        "snapshot_sha256",
    }


@pytest.mark.parametrize("mark,texts", [("del", ["AB"]), ("ins", ["A", "B"])])
def test_boundary_revision_not_whole_paragraph_deletion(mark, texts):
    raw, xml = package(p("A", mark) + p("B"))
    snap = build(raw)
    assert snap.complete and [f.text for f in snap.fragments] == texts
    assert snap.analysis_text == "\n\n".join(texts)
    if mark == "del":
        fragment = snap.fragments[0]
        assert len(fragment.paragraph_anchors) == 2 and len(fragment.joins) == 1
        left, right = fragment.paragraph_anchors
        join = fragment.joins[0]
        assert (join.left, join.right) == (left, right)
        assert resolve(ET.fromstring(xml), join.marker).tag.endswith("}del")
        mapped = api().map_final_span(
            snap, fragment_id=fragment.fragment_id, start=0, end=2, quote="AB"
        )
        assert len(mapped.slices) == 2 and reconstruct(ET.fromstring(xml), mapped) == "AB"
        assert [s.paragraph_anchor for s in mapped.slices] == [left, right]


def test_chain_empty_members_retained_boundaries_and_duplicate_text():
    raw, _ = package(p("A", "del") + p("", "del") + p("B") + p(" ") + p("AB"))
    snap = build(raw)
    assert [f.text for f in snap.fragments] == ["AB", "AB"]
    assert len(snap.fragments[0].paragraph_anchors) == 3
    assert len(snap.fragments[0].joins) == 2
    assert snap.fragments[0].fragment_id != snap.fragments[1].fragment_id
    assert sum(c.status == "empty" for c in snap.coverage) == 1
    assert sum(c.status == "included" for c in snap.coverage) == 4


@pytest.mark.parametrize(
    "body",
    [
        p("last", "del"),
        '<w:p><w:pPr><w:rPr><w:ins w:id="1"/><w:del w:id="2"/>'
        "</w:rPr></w:pPr><w:r><w:t>x</w:t></w:r></w:p>",
        "<w:p><w:ins><w:r><w:t>x</w:t></w:r></w:ins></w:p>",
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r></w:p>' + p("tail"),
        "<w:tbl><w:tr><w:tc>" + p("cell") + "</w:tc></w:tr></w:tbl>",
        '<w:p><w:moveTo w:id="1"><w:r><w:t>x</w:t></w:r></w:moveTo></w:p>',
        "<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>x</w:t></w:r></w:p>",
        '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr/></w:pPrChange></w:pPr></w:p>',
        "<w:p><w:r><w:t>x</w:t></w:r><s:unknown/></w:p>",
        "<w:p><w:r><w:t>x</w:t></w:r>BAD</w:p>",
        '<w:p><w:del w:id="1"><s:unknown/></w:del>BAD</w:p>',
        "<w:p><w:pPr/><w:pPr/></w:p>",
        "<w:p><w:r><w:t><w:tab/></w:t></w:r></w:p>",
        '<w:p><w:r><w:br w:type="unknown"/></w:r></w:p>',
        "<w:p><w:pPr><w:sectPr/></w:pPr></w:p>" + p("next"),
        '<w:ins w:id="1">' + p("block insertion") + "</w:ins>",
    ],
)
def test_unsupported_main_has_no_partially_clean_fragments(body):
    snap = build(package(p("before") + body)[0])
    assert not snap.complete and snap.fragments == () and snap.analysis_text == ""
    assert [(c.status, c.code) for c in snap.coverage if c.anchor is not None] == [
        ("blocked", "unsupported_main_flow")
    ]


def test_metadata_comments_coverage_and_part_gates():
    body = '<w:p><w:bookmarkStart w:id="1" w:name="b"/><w:commentRangeStart w:id="0"/>'
    body += '<w:r><w:rPr><w:b/></w:rPr><w:t>text</w:t><w:commentReference w:id="0"/></w:r>'
    body += '<w:commentRangeEnd w:id="0"/><w:bookmarkEnd w:id="1"/></w:p>'
    raw, _ = package(
        body,
        extra_parts={"word/comments.xml": b"<comments/>"},
        extra_types={
            "word/comments.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
            )
        },
    )
    snap = build(raw)
    assert snap.complete and snap.analysis_text == "text"
    assert len([c for c in snap.coverage if c.anchor is None]) == 4
    assert sum(c.code == "comments_policy" for c in snap.coverage) == 4
    assert any(c.code == "supported_properties" for c in snap.coverage)
    blocked_raw = package(
        body,
        extra_parts={"word/styles.xml": b"<styles/>"},
        extra_types={
            "word/styles.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
            )
        },
    )[0]
    blocked = build(blocked_raw)
    assert not blocked.complete and blocked.analysis_text == "text"
    assert any(c.code == "unread_part" for c in blocked.coverage)


@pytest.mark.parametrize(
    "name,maximum",
    [
        ("max_paragraphs", 2),
        ("max_fragments", 2),
        ("max_pieces", 2),
        ("max_text_characters", 4),
        ("max_coverage_items", 6),
    ],
)
def test_inclusive_output_limits(name, maximum):
    raw = package(p("A") + p("B"))[0]
    assert build(raw, limits=api().FinalViewLimits(**{name: maximum})).complete
    error(
        "view_limit_exceeded",
        lambda: build(raw, limits=api().FinalViewLimits(**{name: maximum - 1})),
    )


@pytest.mark.parametrize("name,maximum", [("max_nodes", 8), ("max_depth", 5)])
def test_parser_limits_count_excluded_nodes_before_pruning(name, maximum):
    raw = package(p("A") + p("B"))[0]
    assert build(raw, limits=api().FinalViewLimits(**{name: maximum})).complete
    projection = import_module("ara.docx_package.projection")
    with pytest.raises(projection.ProjectionError) as caught:
        build(raw, limits=api().FinalViewLimits(**{name: maximum - 1}))
    assert caught.value.code == "projection_limit_exceeded"
    deleted = package('<w:p><w:del w:id="1">' + p("excluded") * 3 + "</w:del></w:p>")[0]
    error(
        "view_limit_exceeded",
        lambda: build(deleted, limits=api().FinalViewLimits(max_paragraphs=3)),
    )


def test_strict_inputs_empty_and_zip_comment_boundary():
    raw = package(p("A"), comment=b"PK\x05\x06" + b"\0" * 18)[0]
    assert build(raw).analysis_text == "A"
    empty = build(package(p(" ") + p(""))[0], limits=api().FinalViewLimits(max_text_characters=1))
    assert empty.complete and not empty.fragments
    for value in (None, bytearray(raw), memoryview(raw), "data"):
        error(
            "invalid_input",
            lambda: api().build_final_snapshot(
                value, document_id=DOC, storage_revision=1, source_sha256="0" * 64
            ),
        )
    for name, value in (
        ("document_id", str(DOC)),
        ("storage_revision", True),
        ("storage_revision", 2**63),
        ("source_sha256", "A" * 64),
        ("limits", {}),
    ):
        kwargs = dict(document_id=DOC, storage_revision=1, source_sha256=sha256(raw).hexdigest())
        kwargs[name] = value
        error("invalid_input", lambda: api().build_final_snapshot(raw, **kwargs))
    error(
        "source_mismatch",
        lambda: api().build_final_snapshot(
            raw, document_id=DOC, storage_revision=1, source_sha256="0" * 64
        ),
    )
    for item in fields(api().FinalViewLimits):
        for bad in (True, 0, -1, 1.5, item.default + 1):
            error("invalid_input", lambda: api().FinalViewLimits(**{item.name: bad}))
    package_api = import_module("ara.docx_package")
    with pytest.raises(package_api.DocxError):
        build(b"bad zip")
    with pytest.raises(package_api.DocxError) as caught:
        build(b"x" * (33554432 + 1))
    assert caught.value.code == "package_limit_exceeded"


@pytest.mark.parametrize(
    "start,end,quote",
    [
        (0, 0, ""),
        (-1, 1, "A"),
        (True, 2, "😀"),
        (0, 99, PRIVATE),
        (2, 3, "😀"),
        (0.0, 1, "A"),
        (0, 1, "wrong"),
        (0, 1, None),
    ],
)
def test_invalid_offsets_never_repaired(start, end, quote):
    snap = build(package(p("A😀B"))[0])
    error(
        "invalid_span",
        lambda: api().map_final_span(
            snap, fragment_id=snap.fragments[0].fragment_id, start=start, end=end, quote=quote
        ),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"profile": "unknown"},
        {"policy_version": "original"},
        {"analysis_text": PRIVATE},
        {"coverage": ()},
        {"complete": False},
        {"snapshot_sha256": "0" * 64},
        {"storage_revision": True},
    ],
)
def test_tampered_snapshots_refused(change):
    snap = build(package(p("A"))[0])
    error(
        "invalid_snapshot",
        lambda: api().map_final_span(
            replace(snap, **change),
            fragment_id=snap.fragments[0].fragment_id,
            start=0,
            end=1,
            quote="A",
        ),
    )


def test_rehashed_semantic_corruption_and_immutable_safe_graph():
    raw = package(p(PRIVATE, "del") + p("B"), main_part="custom/" + PRIVATE + ".xml")[0]
    snap = build(raw)
    fragment = snap.fragments[0]
    for changed in (
        replace(fragment, joins=()),
        replace(fragment, paragraph_anchors=()),
        replace(
            fragment, pieces=(replace(fragment.pieces[0], source_start=1), *fragment.pieces[1:])
        ),
    ):
        broken = rehash(replace(snap, fragments=(changed,)))
        error(
            "invalid_snapshot",
            lambda: api().map_final_span(
                broken, fragment_id=fragment.fragment_id, start=0, end=1, quote=PRIVATE[:1]
            ),
        )
    with pytest.raises(FrozenInstanceError):
        snap.complete = False
    for obj in (snap, fragment, *fragment.pieces, *fragment.joins, *snap.coverage):
        assert not hasattr(obj, "__dict__") and PRIVATE not in repr(obj)
    error(
        "unknown_fragment",
        lambda: api().map_final_span(snap, fragment_id="absent", start=0, end=1, quote="x"),
    )


def test_import_build_map_are_inert_in_fresh_process():
    raw = package(p("A", "del") + p("B"))[0]
    script = """
import builtins,io,os,socket,sys
from pathlib import Path
from hashlib import sha256
from uuid import UUID
raw=sys.stdin.buffer.read()
def forbidden(*args,**kwargs):
    raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=forbidden
from ara.docx_analysis.final_view import build_final_snapshot,map_final_span
s=build_final_snapshot(raw,document_id=UUID(int=1),storage_revision=1,
                       source_sha256=sha256(raw).hexdigest())
map_final_span(s,fragment_id=s.fragments[0].fragment_id,start=0,end=2,quote="AB")
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
