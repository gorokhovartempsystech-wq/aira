"""b2a1 profile dispatch, inert operations and malformed current contexts."""

import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from docx_projection_fixtures import package
from test_docx_final_view import digest, p, rehash
from test_docx_property_history import build

from ara.docx_analysis.final_view import FinalViewError, map_final_span


@pytest.mark.parametrize(
    "content",
    [
        '<w:rPr><w:pPrChange w:id="1"><w:pPr/></w:pPrChange></w:rPr>',
        '<w:rPr><w:rPrChange w:id="1"><w:pPr/></w:rPrChange></w:rPr>',
        '<w:rPr><w:rPrChange w:id="1"><w:rPr/></w:rPrChange>'
        '<w:rPrChange w:id="2"><w:rPr/></w:rPrChange></w:rPr>',
        '<w:rPr><w:rPrChange w:id="1">BAD<w:rPr/></w:rPrChange></w:rPr>',
    ],
)
def test_bad_current_history_container_is_not_excluded_as_a_whole(content):
    s = build(package("<w:p><w:r>" + content + "<w:t>A</w:t></w:r></w:p>")[0])
    assert not s.complete and s.fragments == ()


def test_historical_coverage_is_rejected_by_old_profile_even_with_matching_hashes():
    raw = package(
        '<w:p><w:pPr><w:pPrChange w:id="1"><w:pPr/></w:pPrChange>'
        "</w:pPr><w:r><w:t>A</w:t></w:r></w:p>"
    )[0]
    s = build(raw)
    old_profile = "docx-analysis/final-main-v1"
    f = s.fragments[0]
    record = asdict(f)
    expected_id = {
        key: record[key] for key in ("story_anchor", "flow_anchor", "paragraph_anchors", "joins")
    }
    expected_id.update(
        domain="docx-final-fragment/1",
        source_sha256=s.source_sha256,
        policy_version=s.policy_version,
        profile=old_profile,
    )
    old_id = "lf-" + digest(expected_id)
    old = rehash(
        replace(
            s,
            profile=old_profile,
            fragments=(replace(f, fragment_id=old_id),),
            coverage=tuple(
                replace(c, fragment_id=old_id) if c.fragment_id else c for c in s.coverage
            ),
        )
    )
    with pytest.raises(FinalViewError) as caught:
        map_final_span(old, fragment_id=old_id, start=0, end=1, quote="A")
    assert caught.value.code == "invalid_snapshot"


def test_properties_profile_fresh_process_is_inert():
    raw = package(
        '<w:p><w:r><w:rPr><w:rPrChange w:id="1"><w:rPr><s:ignored/>'
        "</w:rPr></w:rPrChange></w:rPr><w:t>A</w:t></w:r></w:p>" + p("B")
    )[0]
    script = """
import builtins,io,os,socket,sys
from pathlib import Path
from uuid import UUID
from hashlib import sha256
data=sys.stdin.buffer.read()
def forbidden(*args,**kwargs):
    raise AssertionError("Unexpected application I/O")
builtins.open=io.open=Path.open=forbidden
os.getenv=os._Environ.__getitem__=forbidden
socket.socket=socket.create_connection=forbidden
from ara.docx_analysis.final_view import build_properties_snapshot,map_final_span
s=build_properties_snapshot(data,document_id=UUID(int=1),storage_revision=1,
                            source_sha256=sha256(data).hexdigest())
assert s.complete and s.analysis_text=="A\\n\\nB"
map_final_span(s,fragment_id=s.fragments[0].fragment_id,start=0,end=1,quote="A")
blocked={"psycopg","sqlalchemy","onnxruntime","numpy","aira_ml","fastapi"}
assert not any(m.split(".")[0] in blocked for m in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=raw,
        capture_output=True,
        env={"PATH": os.defpath, "PYTHONPATH": str(Path.cwd() / "src")},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b""
