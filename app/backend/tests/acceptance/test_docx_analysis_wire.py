"""Frozen C1C: independent frames and adversarial byte streams."""

import base64
import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

RUN, ATTEMPT = UUID(int=1), UUID(int=2)
SPEC = hashlib.sha256(b"synthetic-spec").hexdigest()


def api():
    return importlib.import_module("ara.docx_analysis_worker.wire")


def binding():
    return api().WireBinding(RUN, ATTEMPT)


def frame(kind, seq=0, **values):
    obj = (
        dict(protocol="aira-worker/1", kind=kind, run_id=str(RUN), attempt_id=str(ATTEMPT), seq=seq)
        | values
    )
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return len(raw).to_bytes(4, "big") + raw


def result_values(raw=b"synthetic-payload"):
    return dict(
        reply_b64=base64.b64encode(raw).decode(), reply_sha256=hashlib.sha256(raw).hexdigest()
    )


def decoder(lane="events"):
    return api().StreamDecoder(
        binding(),
        lane=lane,
        **({"expected_execution_spec_sha256": SPEC} if lane == "events" else {}),
    )


def ready():
    return [
        frame("ready", execution_spec_sha256=SPEC),
        frame("stage", 1, stage="loading_model"),
        frame("stage", 2, stage="analyzing"),
    ]


def feed(d, raw, chunk=65536):
    output = []
    for n in range(0, len(raw), chunk):
        output.extend(d.feed(raw[n : n + chunk]))
    return output


def protocol_error(call):
    with pytest.raises(api().WireError) as error:
        call()
    assert error.value.code == "protocol_error"
    assert "private-sentinel" not in str(error.value)


def test_exact_canonical_encoding_and_one_byte_decoding():
    raw = b'{"quote":"synthetic"}\x00\xff'
    expected = frame("result", 3, **result_values(raw))
    assert (
        api().encode_message(binding(), kind="result", seq=3, values=result_values(raw)) == expected
    )
    d = decoder()
    messages = feed(d, b"".join(ready()) + expected, chunk=1)
    d.finish()
    d.finish()
    assert [m.kind for m in messages] == ["ready", "stage", "stage", "result"]
    assert messages[-1].payload == raw
    assert "reply_b64" not in messages[-1].values
    assert "synthetic" not in repr(messages[-1])
    with pytest.raises((FrozenInstanceError, AttributeError)):
        messages[-1].kind = "error"
    with pytest.raises(TypeError):
        messages[-1].values["reply_sha256"] = "0" * 64


def test_request_and_execution_bytes_retained_without_json_interpretation():
    payload, spec = b"not-JSON\x00", b"synthetic-spec"
    values = dict(
        worker_instance_id=str(UUID(int=3)),
        claim_fence=1,
        request_sha256=hashlib.sha256(payload).hexdigest(),
        execution_spec_sha256=SPEC,
        request_b64=base64.b64encode(payload).decode(),
        execution_spec_b64=base64.b64encode(spec).decode(),
    )
    d = decoder("request")
    (m,) = feed(d, frame("run", **values))
    d.finish()
    assert m.payload == payload and m.execution_spec == spec


@pytest.mark.parametrize("size", [1, 4 * 1024 * 1024])
def test_reply_byte_boundaries(size):
    raw = b"x" * size
    d = decoder()
    messages = feed(d, b"".join(ready()) + frame("result", 3, **result_values(raw)))
    d.finish()
    assert messages[-1].payload == raw


@pytest.mark.parametrize("size", [0, 4 * 1024 * 1024 + 1])
def test_reply_outside_decoded_limits_is_rejected(size):
    d = decoder()
    feed(d, b"".join(ready()))
    protocol_error(lambda: feed(d, frame("result", 3, **result_values(b"x" * size))))


@pytest.mark.parametrize(
    "lane,cap",
    [
        ("request", 12 * 1024 * 1024),
        ("events", 6 * 1024 * 1024),
        ("control", 4096),
        ("status", 4096),
    ],
)
def test_oversize_and_zero_headers_rejected_before_receiving_body(lane, cap):
    for length in (0, cap + 1, 2**32 - 1):
        d = decoder(lane)
        protocol_error(lambda: d.feed(length.to_bytes(4, "big")))
        protocol_error(lambda: d.feed(b""))


@pytest.mark.parametrize(
    "change",
    [
        {"protocol": "other"},
        {"attempt_id": str(UUID(int=99))},
        {"run_id": RUN.hex},
        {"seq": True},
        {"seq": -1},
        {"seq": 1},
        {"seq": 1025},
        {"private": "private-sentinel"},
        {"execution_spec_sha256": "0" * 64},
        {"execution_spec_sha256": []},
    ],
)
def test_closed_root_and_identity(change):
    protocol_error(
        lambda: decoder().feed(frame("ready", **({"execution_spec_sha256": SPEC} | change)))
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b"\xff",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1,"x":2}',
        b'{"x":"\\ud800"}',
        b"[[[[[[]]]]]]",
    ],
)
def test_malformed_json_is_private_and_poisoning(raw):
    d = decoder()
    protocol_error(lambda: d.feed(len(raw).to_bytes(4, "big") + raw))
    protocol_error(d.finish)


def test_noncanonical_input_duplicate_keys_and_truncation():
    good = frame("ready", execution_spec_sha256=SPEC)
    raw = good[4:] + b" "
    protocol_error(lambda: decoder().feed(len(raw).to_bytes(4, "big") + raw))
    duplicate = b'{"protocol":"aira-worker/1","protocol":"aira-worker/1"}'
    protocol_error(lambda: decoder().feed(len(duplicate).to_bytes(4, "big") + duplicate))
    for raw in (b"\x00", good[:-1]):
        d = decoder()
        d.feed(raw)
        protocol_error(d.finish)


@pytest.mark.parametrize("value", ["???=", "eA", "eA==\n", "eB==", "", "eA==AAAA"])
def test_base64_is_strict_and_canonical(value):
    d = decoder()
    feed(d, b"".join(ready()))
    protocol_error(
        lambda: d.feed(
            frame("result", 3, reply_b64=value, reply_sha256=hashlib.sha256(b"x").hexdigest())
        )
    )


def test_digest_mismatch_and_surplus_after_terminal():
    d = decoder()
    feed(d, b"".join(ready()))
    protocol_error(lambda: d.feed(frame("result", 3, reply_b64="eA==", reply_sha256="0" * 64)))
    for suffix in (b"x", frame("error", 1, code="adapter_error")):
        d = decoder()
        d.feed(frame("error", code="adapter_error"))
        protocol_error(lambda: d.feed(suffix))


@pytest.mark.parametrize("prefix", [[], ready()[:1], ready()[:2], ready()])
def test_error_is_terminal_at_each_stage(prefix):
    d = decoder()
    feed(d, b"".join(prefix) + frame("error", len(prefix), code="model_unavailable"))
    d.finish()


def test_wrong_stage_and_missing_terminal_fail():
    protocol_error(lambda: decoder().feed(frame("result", **result_values())))
    d = decoder()
    d.feed(ready()[0])
    protocol_error(lambda: d.feed(frame("stage", 1, stage="analyzing")))
    d = decoder()
    feed(d, b"".join(ready()))
    protocol_error(d.finish)


@pytest.mark.parametrize(
    "deadline,lease",
    [("01", "1"), ("-1", "1"), (str(2**63), "1"), ("1", "2"), (True, "1"), ("1", 1)],
)
def test_control_timestamp_closed_types(deadline, lease):
    protocol_error(
        lambda: decoder("control").feed(frame("permit", deadline_ns=deadline, lease_ns=lease))
    )


def test_control_deadline_pin_sequence_limit_and_eof():
    d = decoder("control")
    for seq in range(512):
        (m,) = d.feed(frame("permit", seq, deadline_ns="100", lease_ns="10"))
        assert m.values["deadline_ns"] == 100
    protocol_error(lambda: d.feed(frame("permit", 512, deadline_ns="100", lease_ns="10")))
    d = decoder("control")
    d.feed(frame("permit", deadline_ns="100", lease_ns="10"))
    protocol_error(lambda: d.feed(frame("permit", 1, deadline_ns="101", lease_ns="10")))
    decoder("control").finish()


def test_guardian_status_types_and_local_errors_are_atomic():
    d = decoder("status")
    for chunk in ("private-sentinel", b"x" * 65537):
        with pytest.raises(api().WireError) as error:
            d.feed(chunk)
        assert error.value.code == "validation_error"
    (message,) = d.feed(frame("closed", exit_kind="clean", exit_code=0, cleanup_confirmed=True))
    assert message.values["cleanup_confirmed"] is True
    d.finish()
    protocol_error(lambda: d.feed(b""))
    for code in (True, 2**31, -(2**31) - 1):
        protocol_error(
            lambda: decoder("status").feed(
                frame("closed", exit_kind="clean", exit_code=code, cleanup_confirmed=True)
            )
        )


def test_binding_is_detached_and_bad_constructor_arguments_rejected():
    b = binding()
    d = api().StreamDecoder(b, lane="events", expected_execution_spec_sha256=SPEC)
    object.__setattr__(b, "run_id", UUID(int=99))
    assert d.feed(ready()[0])[0].binding.run_id == RUN
    for kwargs in (
        {"lane": "unknown"},
        {"lane": "events"},
        {"lane": "control", "expected_execution_spec_sha256": SPEC},
    ):
        with pytest.raises(api().WireError):
            api().StreamDecoder(binding(), **kwargs)
