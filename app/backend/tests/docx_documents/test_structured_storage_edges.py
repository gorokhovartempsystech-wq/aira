"""Structured codec limits and fresh-process isolation are independently enforced."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from test_docx_analysis_storage_codec import api, command, execution, reject
from test_docx_review_v1 import canonical, reply
from test_docx_review_v2 import fixture
from test_docx_structured_storage import result_bundle, source_bundle


@pytest.mark.parametrize("field", ["source", "manifest", "request", "result"])
def test_exact_payload_bounds_include_structured_context(field):
    src, a, r = result_bundle()
    if field == "source":
        caps = api().CodecLimits(max_source_bytes=len(src.source_data))
        assert api().restore_source(src, limits=caps).snapshot.profile == src.profile
        reject(
            "codec_limit_exceeded",
            lambda: api().restore_source(
                src, limits=replace(caps, max_source_bytes=len(src.source_data) - 1)
            ),
        )
    elif field == "manifest":
        caps = api().CodecLimits(max_manifest_bytes=len(src.snapshot_data))
        assert api().restore_source(src, limits=caps).snapshot.profile == src.profile
        reject(
            "codec_limit_exceeded",
            lambda: api().restore_source(
                src, limits=replace(caps, max_manifest_bytes=len(src.snapshot_data) - 1)
            ),
        )
    else:
        size = (
            max(len(a.request_data), len(r.result_data))
            if field == "result"
            else len(a.request_data)
        )
        caps = api().CodecLimits(review=api().CodecLimits().review.__class__(max_wire_bytes=size))
        if field == "request":
            assert api().prepare_attempt(src, attempt_id=a.attempt_id, limits=caps) == a
        else:
            assert api().restore_result(src, a, r, limits=caps).wire_json == r.result_data
        reduced = replace(caps, review=replace(caps.review, max_wire_bytes=size - 1))
        if field == "request":
            reject(
                "codec_limit_exceeded",
                lambda: api().prepare_attempt(src, attempt_id=a.attempt_id, limits=reduced),
            )
        else:
            reject("codec_limit_exceeded", lambda: api().restore_result(src, a, r, limits=reduced))


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_version", True),
        ("profile", None),
        ("policy_version", []),
        ("storage_revision", False),
    ],
)
def test_strict_record_scalars_are_checked_before_profile_selection(field, value):
    src = source_bundle()
    reject("corrupt_record", lambda: api().restore_source(replace(src, **{field: value})))


@pytest.mark.parametrize("field", ["source_data", "command_data", "execution_spec"])
def test_rehashed_mismatched_source_command_and_execution_still_fail(field):
    src, a, r = result_bundle()
    if field == "source_data":
        from test_docx_visible_lists import paragraph
        from test_docx_visible_unlisted import source

        raw, _ = source(paragraph("Different source"))
        hashfield = "source_sha256"
    else:
        body = json.loads(getattr(src, field))
        if field == "command_data":
            body["storage_revision"] = "99"
            hashfield = "command_sha256"
        else:
            body["models_version"] = "changed-model"
            hashfield = "execution_spec_sha256"
        raw = canonical(body)
    changed = replace(src, **{field: raw, hashfield: sha256(raw).hexdigest()})
    reject("corrupt_record", lambda: api().restore_result(changed, a, r))


def test_unknown_dtos_incomplete_sources_and_marker_only_are_not_successful_records():
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_unlisted import source

    from ara.docx_analysis.review import ReviewError
    from ara.docx_analysis.visible_main import VisibleViewError

    raw, _, s = fixture()
    for fake in (None, object(), replace(s, profile="unknown/v1")):
        with pytest.raises(VisibleViewError) as e:
            api().capture_source(raw, fake, command=command(s), execution=execution())
        assert e.value.code == "invalid_snapshot"
    for body, code in (
        (paragraph("", level=0), "empty_document"),
        (paragraph("Unsupported", level=1), "unsupported_document"),
    ):
        raw, _ = source(body)
        s = build(raw)
        with pytest.raises(ReviewError) as e:
            api().capture_source(raw, s, command=command(s), execution=execution())
        assert e.value.code == code


def test_fragment_cap_still_counts_literal_fragments_and_does_not_count_labels_as_fragments():
    raw, _, s = fixture()
    assert len(s.fragments) == 2 and len(s.lists) == 1
    caps = api().CodecLimits(max_fragments=2)
    src = api().capture_source(raw, s, command=command(s), execution=execution(), limits=caps)
    assert api().restore_source(src, limits=caps).snapshot == s
    reject(
        "codec_limit_exceeded",
        lambda: api().restore_source(src, limits=replace(caps, max_fragments=1)),
    )


def test_fresh_process_roundtrips_without_implicit_io_database_or_model_imports():
    raw, _, _ = fixture()
    script = """
import builtins,io,os,socket,subprocess,sys,json
from pathlib import Path
from hashlib import sha256
from uuid import UUID
from xml.etree import ElementTree as ET
data=sys.stdin.buffer.read()
def forbidden(*a,**kw): raise AssertionError('Unexpected I/O')
builtins.open=io.open=Path.open=os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=subprocess.Popen=ET.tostring=forbidden
from ara.docx_analysis.visible_lists import build_list_snapshot
from ara.docx_analysis.storage_codec import *
s=build_list_snapshot(data,document_id=UUID(int=1),storage_revision=7,source_sha256=sha256(data).hexdigest())
c=SavedCheckCommand(s.document_id,UUID(int=2),UUID(int=3),UUID(int=4),1,0,7,s.source_sha256)
x=ExecutionSpec('fixture','0.1.0','synthetic-1','1'*64,'2'*64)
src=capture_source(data,s,command=c,execution=x)
assert restore_source(src).snapshot==s
a=prepare_attempt(src,attempt_id=UUID(int=1))
n=len(s.fragments)
body=dict(engine='0.1.0',models='synthetic-1',issues=[],questions=[],checked=dict(fragments=n,active=n,skipped_status=0),seconds=0)
r=capture_result(src,a,reply=json.dumps(body).encode())
out=restore_result(src,a,r)
assert json.loads(out.wire_json)['document_context']['lists'][0]['label']=='1.'
assert not out.no_findings
blocked={'psycopg','sqlalchemy','onnxruntime','numpy','aira_ml','fastapi','PIL'}
assert not any(n.split('.')[0] in blocked for n in sys.modules)
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


def test_private_context_and_document_content_never_appear_in_storage_reprs():
    src, a, r = result_bundle()
    for value in (src, a, r, api().restore_source(src), api().restore_result(src, a, r)):
        assert "PRIVATE" not in repr(value) and "Other 😀" not in repr(value)
        assert "Synthetic explanation" not in repr(value)


@pytest.mark.parametrize("fault", ["source_hash", "manifest_hash", "oversized_buffer"])
def test_structured_dispatch_does_not_rebuild_source_before_record_buffers_are_valid(
    monkeypatch, fault
):
    from importlib import import_module

    src = source_bundle()

    def forbidden(*a, **kw):
        raise AssertionError("Unvalidated record reached source parser")

    monkeypatch.setattr(
        import_module("ara.docx_analysis.compatibility_contexts._read"),
        "build_compatibility_view",
        forbidden,
    )
    if fault == "source_hash":
        src = replace(src, source_sha256="0" * 64)
        code = "corrupt_record"
    elif fault == "manifest_hash":
        src = replace(src, snapshot_sha256="0" * 64)
        code = "corrupt_record"
    else:
        src = replace(src, execution_spec=b"x" * 4097)
        code = "codec_limit_exceeded"
    reject(code, lambda: api().restore_source(src))


@pytest.mark.parametrize("suffix", ["tab", "space", "nothing"])
def test_generated_cost_includes_blank_list_items_and_exact_suffix_policy(suffix):
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_unlisted import DEFS, source

    raw, _ = source(
        paragraph("") + paragraph("Text"),
        DEFS.replace("<w:lvlText", f'<w:suff w:val="{suffix}"/><w:lvlText'),
    )
    s = build(raw)
    assert s.complete and len(s.lists) == 2 and s.lists[0].fragment_ids == ()
    cost = 4 + 2 * (2 + (suffix != "nothing"))
    caps = api().CodecLimits(max_text_characters=cost)
    src = api().capture_source(raw, s, command=command(s), execution=execution(), limits=caps)
    assert api().restore_source(src, limits=caps).snapshot == s
    reject(
        "codec_limit_exceeded",
        lambda: api().restore_source(src, limits=replace(caps, max_text_characters=cost - 1)),
    )


def test_note_links_and_split_list_fragments_survive_restore_and_rehashed_link_forgery_fails():
    from test_docx_note_catalog import note
    from test_docx_review_v2 import context
    from test_docx_visible_lists import build, paragraph
    from test_docx_visible_main import R
    from test_docx_visible_notes import note_xml, ref
    from test_docx_visible_unlisted import source

    raw, _ = source(
        paragraph(atoms="<w:t>Before</w:t>" + ref() + "<w:t>After</w:t>"),
        extra_parts={"custom/Foot.xml": note_xml(note())},
        extra_types={
            "custom/Foot.xml": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
            )
        },
        links=[
            {"Id": "N", "Type": R + "numbering", "Target": "Numbers.xml"},
            {"Id": "F", "Type": R + "footnotes", "Target": "Foot.xml"},
        ],
    )
    s = build(raw)
    assert s.complete and len(s.references) == 1 and len(s.lists[0].fragment_ids) == 2
    src = api().capture_source(raw, s, command=command(s), execution=execution())
    assert api().restore_source(src).snapshot == s
    attempt = api().prepare_attempt(src, attempt_id=UUID(int=1))
    n = len(s.fragments)
    result = api().capture_result(
        src,
        attempt,
        reply=canonical(reply(s, issues=[], checked=dict(fragments=n, active=n, skipped_status=0))),
    )
    out = json.loads(api().restore_result(src, attempt, result).wire_json)
    assert out["document_context"] == context(s)
    out["document_context"]["note_references"][0]["target_anchor"] = out["document_context"][
        "note_references"
    ][0]["reference_anchor"]
    changed = canonical(out)
    reject(
        "corrupt_record",
        lambda: api().restore_result(
            src,
            attempt,
            replace(result, result_data=changed, result_sha256=sha256(changed).hexdigest()),
        ),
    )
