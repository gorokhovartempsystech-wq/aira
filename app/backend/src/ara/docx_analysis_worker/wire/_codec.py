"""Closed flat JSON frames; binary payloads stay opaque to this transport."""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID

MIB = 1024 * 1024
COMMON = frozenset(("protocol", "kind", "run_id", "attempt_id", "seq"))
SCHEMAS = {
    "run": (
        "request",
        12 * MIB,
        (
            "worker_instance_id",
            "claim_fence",
            "request_sha256",
            "execution_spec_sha256",
            "request_b64",
            "execution_spec_b64",
        ),
    ),
    "ready": ("events", 4096, ("execution_spec_sha256",)),
    "stage": ("events", 4096, ("stage",)),
    "result": ("events", 6 * MIB, ("reply_sha256", "reply_b64")),
    "error": ("events", 4096, ("code",)),
    "permit": ("control", 4096, ("deadline_ns", "lease_ns")),
    "stop": ("control", 4096, ("reason",)),
    "closed": ("status", 4096, ("exit_kind", "exit_code", "cleanup_confirmed")),
}
CAPS = {"request": 12 * MIB, "events": 6 * MIB, "control": 4096, "status": 4096}
TOTALS = {"request": 12 * MIB, "events": 6 * MIB + 12288, "control": MIB, "status": 4096}
COUNTS = {"request": 1, "events": 4, "control": 512, "status": 1}


class WireError(Exception):
    def __init__(self, code="protocol_error"):
        self.code = "validation_error" if code == "validation_error" else "protocol_error"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class WireBinding:
    run_id: UUID
    attempt_id: UUID


@dataclass(frozen=True, slots=True)
class WireMessage:
    binding: WireBinding
    kind: str
    seq: int
    values: object = field(repr=False)
    payload: bytes | None = field(default=None, repr=False)
    execution_spec: bytes | None = field(default=None, repr=False)


def binding_copy(value):
    if type(value) is not WireBinding or any(
        type(getattr(value, name, None)) is not UUID for name in ("run_id", "attempt_id")
    ):
        raise WireError("validation_error")
    return WireBinding(value.run_id, value.attempt_id)


def require(good):
    if not good:
        raise WireError()


def digest(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def unpack64(value, sha, maximum):
    require(type(value) is str and 0 < len(value) <= 4 * ((maximum + 2) // 3))
    require(len(value) % 4 == 0 and digest(sha))
    padding = 2 if value.endswith("==") else 1 if value.endswith("=") else 0
    require(1 <= len(value) // 4 * 3 - padding <= maximum)
    raw = base64.b64decode(value, validate=True)
    require(base64.b64encode(raw).decode("ascii") == value)
    require(hashlib.sha256(raw).hexdigest() == sha)
    return raw


def timestamp(value):
    require(
        type(value) is str
        and 1 <= len(value) <= 19
        and value.isascii()
        and value.isdecimal()
        and (value == "0" or not value.startswith("0"))
    )
    result = int(value)
    require(result <= 2**63 - 1)
    return result


def message(binding, obj):
    require(type(obj) is dict and type(obj.get("kind")) is str)
    kind = obj["kind"]
    require(kind in SCHEMAS)
    _, _, names = SCHEMAS[kind]
    require(obj.keys() == COMMON | frozenset(names))
    require(obj["protocol"] == "aira-worker/1")
    require(obj["run_id"] == str(binding.run_id) and obj["attempt_id"] == str(binding.attempt_id))
    require(type(obj["seq"]) is int and 0 <= obj["seq"] <= 1024)
    values = {name: obj[name] for name in names}
    payload = spec = None
    if kind == "run":
        worker = values["worker_instance_id"]
        require(type(worker) is str and str(UUID(worker)) == worker)
        require(type(values["claim_fence"]) is int and values["claim_fence"] == 1)
        payload = unpack64(values.pop("request_b64"), values["request_sha256"], 8 * MIB)
        spec = unpack64(values.pop("execution_spec_b64"), values["execution_spec_sha256"], 4096)
    elif kind == "ready":
        require(digest(values["execution_spec_sha256"]))
    elif kind == "stage":
        require(type(values["stage"]) is str and values["stage"] in ("loading_model", "analyzing"))
    elif kind == "result":
        payload = unpack64(values.pop("reply_b64"), values["reply_sha256"], 4 * MIB)
    elif kind == "error":
        require(
            type(values["code"]) is str
            and values["code"]
            in (
                "model_unavailable",
                "model_input_limit_exceeded",
                "adapter_error",
                "analysis_limit_exceeded",
            )
        )
    elif kind == "permit":
        values = {key: timestamp(value) for key, value in values.items()}
        require(values["lease_ns"] <= values["deadline_ns"])
    elif kind == "stop":
        require(
            type(values["reason"]) is str
            and values["reason"] in ("user", "deadline", "lease", "storage", "shutdown", "protocol")
        )
    else:
        require(
            type(values["exit_kind"]) is str
            and values["exit_kind"] in ("clean", "stopped", "crashed")
        )
        require(type(values["exit_code"]) is int and -(2**31) <= values["exit_code"] < 2**31)
        require(type(values["cleanup_confirmed"]) is bool)
    return WireMessage(
        binding_copy(binding), kind, obj["seq"], MappingProxyType(values), payload, spec
    )


def encode_message(binding, *, kind, seq, values):
    binding = binding_copy(binding)
    try:
        require(type(kind) is str and kind in SCHEMAS)
        require(type(values) is dict and len(values) <= 6)
        obj = dict(
            protocol="aira-worker/1",
            kind=kind,
            run_id=str(binding.run_id),
            attempt_id=str(binding.attempt_id),
            seq=seq,
        )
        require(values.keys() == frozenset(SCHEMAS[kind][2]))
        obj.update(values)
        message(binding, obj)
        raw = canonical(obj)
        require(len(raw) <= SCHEMAS[kind][1])
        return len(raw).to_bytes(4, "big") + raw
    except Exception:
        raise WireError("validation_error") from None


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result)
        result[key] = value
    return result


def no_number(value):
    raise WireError()


def preflight(raw):
    # All schemas are flat. Reject nesting and excess fields before json allocates nodes.
    quoted = escaped = False
    depth = commas = 0
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (123, 91):
            depth += 1
            require(depth <= 1 and byte == 123)
        elif byte in (125, 93):
            depth -= 1
            require(depth >= 0 and byte == 125)
        elif byte == 44:
            commas += 1
            require(commas <= 10)


def decode(binding, raw):
    preflight(raw)
    obj = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=no_number,
        parse_float=no_number,
    )
    result = message(binding, obj)
    require(len(raw) <= SCHEMAS[result.kind][1] and canonical(obj) == raw)
    return result
