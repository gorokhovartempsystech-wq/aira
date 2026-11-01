"""Bounded malformed structures, caller isolation and side-effect-free codec."""

import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ara.docx_package import DocxError
from ara.docx_package.checkpoint import (
    CheckpointError,
    decode_metadata,
    encode_metadata,
)
from ara.docx_package.editor import EditorError
from tests.acceptance.test_docx_checkpoint_metadata import sample


@pytest.mark.parametrize("kind", ["cycle", "depth", "surrogate", "nul", "giant_revision"])
def test_invalid_nested_shapes_fail_before_json_serialization(kind):
    raw, _, wire = sample()
    point = wire["selection"]["anchor"]
    if kind == "cycle":
        point["anchor"]["path"] = [wire]
    if kind == "depth":
        point["anchor"]["path"] = [[[[0]]]]
    if kind == "surrogate":
        point["anchor"]["part_name"] = "SYNTHETIC_PRIVATE\ud800"
    if kind == "nul":
        point["anchor"]["part_name"] = "word/\x00.xml"
    if kind == "giant_revision":
        wire["origin"]["session_revision"] = "1" * 1000000
    with pytest.raises(CheckpointError) as caught:
        decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase="working")
    assert caught.value.code == "invalid_input" and "SYNTHETIC_PRIVATE" not in repr(caught.value)


def test_out_of_range_selection_and_invalid_package_are_not_trusted():
    raw, _, wire = sample()
    invalid = deepcopy(wire)
    invalid["selection"]["focus"]["offset"] = 999
    with pytest.raises(EditorError) as caught:
        decode_metadata(invalid, data=raw, saved_sha256="0" * 64, phase="working")
    assert caught.value.code == "invalid_selection"
    with pytest.raises(DocxError):
        decode_metadata(wire, data=b"bad package", saved_sha256="0" * 64, phase="working")


def test_decoded_and_encoded_copies_never_share_anchors_or_paths():
    raw, _, wire = sample()
    original = deepcopy(wire)
    first = decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase="working")
    second = decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase="working")
    encoded = encode_metadata(first, data=raw, saved_sha256="0" * 64, phase="working")
    object.__setattr__(first.selection.anchor.anchor, "path", (999,))
    assert encode_metadata(second, data=raw, saved_sha256="0" * 64, phase="working") == original
    assert encoded == original and wire == original
    with pytest.raises(EditorError):
        encode_metadata(first, data=raw, saved_sha256="0" * 64, phase="working")


def test_pending_fields_are_strict_and_hash_does_not_claim_to_be_a_verified_receipt():
    raw, _, wire = sample(True)
    original = deepcopy(wire)
    decoded = decode_metadata(wire, data=raw, saved_sha256="0" * 64, phase="pending")
    assert decoded.pending.request_sha256 == "c" * 64
    for field, value in (("operation_id", 0), ("request_sha256", "A" * 64)):
        invalid = deepcopy(original)
        invalid["pending"][field] = value
        with pytest.raises(CheckpointError):
            decode_metadata(invalid, data=raw, saved_sha256="0" * 64, phase="pending")


def test_first_codec_import_and_call_do_not_use_external_io():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid
import hashlib,zipfile,xml.etree.ElementTree,typing
from pathlib import Path
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes')):
    setattr(obj,name,forbidden)
from ara.docx_package.checkpoint import CheckpointMetadata,CheckpointOrigin
from ara.docx_package.checkpoint import encode_metadata,decode_metadata
from ara.docx_package.creation import create_docx
from ara.docx_package.editor import EditorSession
raw=create_docx()
selection=EditorSession(raw).snapshot().selection
value=CheckpointMetadata(selection,CheckpointOrigin(uuid.UUID('a'*32),0,0))
wire=encode_metadata(value,data=raw,saved_sha256='0'*64,phase='working')
assert decode_metadata(wire,data=raw,saved_sha256='0'*64,phase='working')==value
"""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout
