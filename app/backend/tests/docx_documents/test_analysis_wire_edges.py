"""Wire limits, parser continuity and private diagnostics beyond frozen acceptance."""

import base64
import hashlib
import subprocess
import sys
import traceback
from pathlib import Path

import pytest

from tests.acceptance.test_docx_analysis_wire import (
    SPEC,
    api,
    binding,
    decoder,
    feed,
    frame,
    protocol_error,
    ready,
    result_values,
)


@pytest.mark.parametrize("size,valid", [(8 * 1024 * 1024, True), (8 * 1024 * 1024 + 1, False)])
def test_decoded_request_cap(size, valid):
    raw, spec = b"x" * size, b"synthetic-spec"
    values = dict(
        worker_instance_id=str(binding().run_id),
        claim_fence=1,
        request_sha256=hashlib.sha256(raw).hexdigest(),
        execution_spec_sha256=SPEC,
        request_b64=base64.b64encode(raw).decode(),
        execution_spec_b64=base64.b64encode(spec).decode(),
    )
    d = decoder("request")
    if valid:
        assert feed(d, frame("run", **values))[0].payload == raw
        d.finish()
    else:
        protocol_error(lambda: feed(d, frame("run", **values)))


def test_spec_cap_and_encoder_reject_invalid_frames():
    for values in (
        result_values(b""),
        result_values() | {"extra": "private-sentinel"},
        result_values() | {"reply_sha256": "0" * 64},
    ):
        with pytest.raises(api().WireError) as error:
            api().encode_message(binding(), kind="result", seq=3, values=values)
        assert error.value.code == "validation_error"
    spec = b"x" * 4097
    values = dict(
        worker_instance_id=str(binding().run_id),
        claim_fence=1,
        request_b64="eA==",
        request_sha256=hashlib.sha256(b"x").hexdigest(),
        execution_spec_b64=base64.b64encode(spec).decode(),
        execution_spec_sha256=hashlib.sha256(spec).hexdigest(),
    )
    protocol_error(lambda: feed(decoder("request"), frame("run", **values)))


def test_invalid_local_chunk_does_not_disturb_partial_header():
    d = decoder()
    raw = ready()[0]
    assert not d.feed(raw[:2])
    with pytest.raises(api().WireError):
        d.feed(memoryview(b"private-sentinel"))
    assert d.feed(raw[2:])[0].kind == "ready"


@pytest.mark.parametrize("chunk", [2, 3, 4, 5, 7, 63, 65536])
def test_frame_chunk_boundaries(chunk):
    d = decoder()
    raw = b"x" * 70000
    out = feed(d, b"".join(ready()) + frame("result", 3, **result_values(raw)), chunk)
    assert out[-1].payload == raw
    d.finish()


def test_control_stop_is_terminal_and_eof_is_distinct_from_bad_frame():
    d = decoder("control")
    d.feed(frame("stop", reason="user"))
    d.finish()
    protocol_error(lambda: d.feed(frame("permit", 1, deadline_ns="100", lease_ns="10")))
    d = decoder("control")
    d.feed(b"\x00")
    protocol_error(d.finish)


def test_peer_parser_exceptions_do_not_disclose_bytes_in_traceback():
    raw = b'{"private-sentinel": [1,2,3]}'
    with pytest.raises(api().WireError) as caught:
        decoder().feed(len(raw).to_bytes(4, "big") + raw)
    assert "private-sentinel" not in "".join(traceback.format_exception(caught.value))


def test_fresh_import_and_construction_do_not_start_runtime_io():
    root = Path(__file__).resolve().parents[2]
    script = r"""
import base64, builtins, hashlib, json, os, socket, subprocess, threading, time
from dataclasses import dataclass
from uuid import UUID
def forbidden(*a, **kw): raise AssertionError("runtime IO")
builtins.open = forbidden
os.getenv = forbidden
os._Environ.__getitem__ = forbidden
socket.socket = subprocess.Popen = threading.Thread.start = forbidden
time.time = time.monotonic = time.monotonic_ns = forbidden
from ara.docx_analysis_worker.wire import WireBinding, StreamDecoder
StreamDecoder(WireBinding(UUID(int=1),UUID(int=2)),lane="control").finish()
assert not any(n.startswith(("sqlalchemy", "psycopg", "onnxruntime", "ara.models"))
               for n in __import__("sys").modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=root / "src", capture_output=True, timeout=15
    )
    assert result.returncode == 0, result.stderr.decode()
