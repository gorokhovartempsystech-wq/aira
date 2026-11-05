"""Bound canonical storage JSON before decode, allocation or hashing."""

import json
from dataclasses import fields
from hashlib import sha256
from uuid import UUID

from ara.docx_analysis.visible_main._canonical import tokens

from ._models import (
    EncodedValue,
    ExecutionSpec,
    RetryCheckCommand,
    SavedCheckCommand,
    StorageCodecError,
    checked,
    counter,
    digest,
    require,
)


def raw_bytes(data, maximum, code="corrupt_record"):
    require(type(data) is bytes and bool(data), code)
    require(len(data) <= maximum, "codec_limit_exceeded")


def hashed(data, expected, maximum):
    raw_bytes(data, maximum)
    require(digest(expected) and sha256(data).hexdigest() == expected, "corrupt_record")


def encoded(value, maximum, *, omit_hash=False):
    output = bytearray()
    try:
        for t in tokens(value, omit_hash=omit_hash):
            raw = t.encode("utf-8")
            require(len(output) + len(raw) <= maximum, "codec_limit_exceeded")
            output.extend(raw)
    except UnicodeError:
        raise StorageCodecError("invalid_input") from None
    data = bytes(output)
    return EncodedValue(data, sha256(data).hexdigest())


def valid_command(command):
    require(type(command) in (SavedCheckCommand, RetryCheckCommand))
    command.__post_init__()
    return command


def valid_execution(execution):
    require(type(execution) is ExecutionSpec)
    execution.__post_init__()
    return execution


def command_body(command):
    valid_command(command)
    body = dict(
        schema_version="docx-analysis-command/1",
        kind="saved" if type(command) is SavedCheckCommand else "retry",
    )
    for f in fields(command):
        v = getattr(command, f.name)
        body[f.name] = str(v) if type(v) in (UUID, int) else v
    return body


def execution_body(execution):
    valid_execution(execution)
    return dict(schema_version="docx-analysis-execution/1") | {
        f.name: getattr(execution, f.name) for f in fields(execution)
    }


def encode_command(command, *, limits=None):
    limits = checked(limits)
    return encoded(command_body(command), limits.max_command_bytes)


def encode_execution(execution, *, limits=None):
    limits = checked(limits)
    return encoded(execution_body(execution), limits.max_execution_bytes)


def pairs(items):
    out = {}
    for k, v in items:
        require(k not in out, "corrupt_record")
        out[k] = v
    return out


def constant(value):
    raise StorageCodecError("corrupt_record")


def parsed(data, expected, maximum):
    hashed(data, expected, maximum)
    try:
        string = data.decode("utf-8")
        inside = escaped = False
        depth = 0
        for c in string:
            if inside:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    inside = False
            elif c == '"':
                inside = True
            elif c in "[{":
                depth += 1
                require(depth <= 8, "corrupt_record")
            elif c in "]}":
                depth -= 1
        body = json.loads(string, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError, OverflowError) as e:
        if type(e) is StorageCodecError:
            raise
        raise StorageCodecError("corrupt_record") from None
    require(type(body) is dict, "corrupt_record")
    return body


def canonical_uuid(value):
    require(type(value) is str and len(value) == 36, "corrupt_record")
    try:
        result = UUID(value)
    except ValueError:
        raise StorageCodecError("corrupt_record") from None
    require(str(result) == value, "corrupt_record")
    return result


def canonical_counter(value, minimum):
    require(
        type(value) is str and 1 <= len(value) <= 19 and value.isascii() and value.isdecimal(),
        "corrupt_record",
    )
    result = int(value)
    require(counter(result, minimum) and str(result) == value, "corrupt_record")
    return result


def version(body, expected):
    value = body.get("schema_version")
    require(type(value) is str, "corrupt_record")
    require(value == expected, "unsupported_version")


def decode_command(data, *, expected_sha256, limits=None):
    limits = checked(limits)
    body = parsed(data, expected_sha256, limits.max_command_bytes)
    version(body, "docx-analysis-command/1")
    kind = body.get("kind")
    require(type(kind) is str and kind in ("saved", "retry"), "corrupt_record")
    cls = SavedCheckCommand if kind == "saved" else RetryCheckCommand
    require(
        set(body) == {"schema_version", "kind"} | {f.name for f in fields(cls)}, "corrupt_record"
    )
    values = {}
    for f in fields(cls):
        v = body[f.name]
        if f.name.endswith("_id"):
            v = canonical_uuid(v)
        elif f.name in ("command_sequence", "session_revision", "storage_revision"):
            v = canonical_counter(v, 0 if f.name == "session_revision" else 1)
        values[f.name] = v
    try:
        result = cls(**values)
    except StorageCodecError:
        raise StorageCodecError("corrupt_record") from None
    require(encoded(command_body(result), limits.max_command_bytes).data == data, "corrupt_record")
    return result


def decode_execution(data, *, expected_sha256, limits=None):
    limits = checked(limits)
    body = parsed(data, expected_sha256, limits.max_execution_bytes)
    version(body, "docx-analysis-execution/1")
    require(
        set(body) == {"schema_version"} | {f.name for f in fields(ExecutionSpec)}, "corrupt_record"
    )
    try:
        result = ExecutionSpec(**{f.name: body[f.name] for f in fields(ExecutionSpec)})
    except StorageCodecError:
        raise StorageCodecError("corrupt_record") from None
    require(
        encoded(execution_body(result), limits.max_execution_bytes).data == data, "corrupt_record"
    )
    return result
