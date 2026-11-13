"""The secret preamble never enters persisted run JSON or diagnostics."""

import base64
import hashlib
import secrets
from uuid import uuid4

import pytest

from ara.docx_analysis_worker.wire import WireBinding, encode_message
from ara.model_protection import ModelProtectionError
from ara.model_protection.private_bootstrap import (
    MAGIC,
    SIZE,
    ProtectedRequestDecoder,
    wrap_request,
)


def frame():
    binding = WireBinding(uuid4(), uuid4())
    request, spec = b"synthetic request", b"synthetic execution"
    raw = encode_message(
        binding,
        kind="run",
        seq=0,
        values=dict(
            worker_instance_id=str(uuid4()),
            claim_fence=1,
            request_sha256=hashlib.sha256(request).hexdigest(),
            execution_spec_sha256=hashlib.sha256(spec).hexdigest(),
            request_b64=base64.b64encode(request).decode(),
            execution_spec_b64=base64.b64encode(spec).decode(),
        ),
    )
    return binding, raw


@pytest.mark.parametrize("chunk", [1, 2, 7, SIZE - 1, SIZE, SIZE + 1, 65536])
def test_split_preamble_then_unchanged_request(chunk):
    binding, raw = frame()
    key = secrets.token_bytes(32)
    data, decoder, messages = wrap_request(key, raw), ProtectedRequestDecoder(binding), []
    for offset in range(0, len(data), chunk):
        messages.extend(decoder.feed(data[offset : offset + chunk]))
    decoder.finish()
    assert len(messages) == 1 and messages[0].payload == b"synthetic request"
    assert key.hex() not in repr(messages[0]) + repr(decoder)
    assert decoder.take_key() == key
    with pytest.raises(ModelProtectionError):
        decoder.take_key()


def test_all_short_preambles_fail_without_a_key():
    binding, raw = frame()
    data = wrap_request(secrets.token_bytes(32), raw)
    for length in range(SIZE):
        decoder = ProtectedRequestDecoder(binding)
        decoder.feed(data[:length])
        with pytest.raises(ModelProtectionError):
            decoder.finish()
        with pytest.raises(ModelProtectionError):
            decoder.take_key()


def test_unprotected_or_corrupted_request_cannot_release_key():
    binding, raw = frame()
    key = secrets.token_bytes(32)
    for data in (raw, b"!" + wrap_request(key, raw)[1:], wrap_request(key, raw) + b"trailing"):
        decoder = ProtectedRequestDecoder(binding)
        with pytest.raises(Exception):
            decoder.feed(data)
            decoder.finish()
        with pytest.raises(ModelProtectionError):
            decoder.take_key()


def test_private_key_without_complete_run_frame_is_not_a_permit():
    binding, _ = frame()
    decoder = ProtectedRequestDecoder(binding)
    decoder.feed(MAGIC + secrets.token_bytes(32))
    with pytest.raises(ModelProtectionError):
        decoder.take_key()
    with pytest.raises(ModelProtectionError):
        decoder.finish()
