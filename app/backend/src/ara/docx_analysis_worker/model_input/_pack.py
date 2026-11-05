"""Verify supplied immutable package bytes against a separately trusted digest."""

import json
import math
import re
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

from ._errors import ModelInputError, require

FOLDERS = ("embedder", "pair", "nli")
NAMES = (
    "model.int8.onnx",
    "tokenizer.json",
    "config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.txt",
)
PATHS = frozenset(f + "/" + n for f in FOLDERS for n in NAMES)
REQUIRED = frozenset(f + "/" + n for f in FOLDERS for n in NAMES[:2])


@dataclass(frozen=True, slots=True)
class VerifiedPack:
    models_version: str
    sha256: str
    manifest_bytes: bytes = field(repr=False)
    files: Mapping[str, bytes] = field(repr=False)


def _text(value, limit):
    require(
        type(value) is str and bool(value.strip()) and len(value) <= limit and "\x00" not in value
    )
    value.encode("utf-8")


def _hash(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        require(k not in out)
        out[k] = v
    return out


def _constant(value):
    raise ModelInputError("model_unavailable")


def _json(raw):
    decoded = raw.decode("utf-8")
    inside = escaped = False
    depth = 0
    for c in decoded:
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
            require(depth <= 16)
        elif c in "]}":
            depth -= 1
    value = json.loads(decoded, object_pairs_hook=_pairs, parse_constant=_constant)

    def finite(item):
        if type(item) is float:
            require(math.isfinite(item))
        elif type(item) is str:
            item.encode("utf-8")
        elif type(item) is dict:
            for k, v in item.items():
                finite(k)
                finite(v)
        elif type(item) is list:
            for v in item:
                finite(v)

    finite(value)
    return value


def _verify(manifest, files, expected_sha256):
    require(type(manifest) is bytes and 0 < len(manifest) <= 1048576)
    _hash(expected_sha256)
    require(sha256(manifest).hexdigest() == expected_sha256)
    m = _json(manifest)
    require(
        type(m) is dict
        and set(m) == {"name", "version", "built", "runtime", "models", "files", "total_mb"}
    )
    require(m["name"] == "aira-models")
    _text(m["version"], 128)
    for name in ("built", "runtime"):
        _text(m[name], 4096)
    models = m["models"]
    require(type(models) is dict and set(models) == set(FOLDERS))
    for name in FOLDERS:
        model = models[name]
        require(type(model) is dict)
        _text(model.get("license"), 4096)
    require(type(models["embedder"].get("dim")) is int and models["embedder"]["dim"] > 0)
    require(models["nli"].get("labels") == ["entailment", "neutral", "contradiction"])
    labels = models["pair"].get("labels")
    require(type(labels) is list and len(labels) == 4 and all(type(v) is str for v in labels))
    require(set(labels) == {"keep", "unrelated", "update", "contradiction"})
    temperature = models["pair"].get("temperature", 1.0)
    require(type(temperature) in (int, float) and math.isfinite(temperature) and temperature > 0)
    records = m["files"]
    require(type(records) is dict and REQUIRED <= records.keys() <= PATHS and len(records) <= 32)
    require(type(files) is dict and files.keys() == records.keys())
    total, verified = 0, {}
    for path, record in records.items():
        require(type(record) is dict and set(record) == {"bytes", "sha256"})
        size = record["bytes"]
        maximum = 16777216 if path.endswith("/tokenizer.json") else 536870912
        require(type(size) is int and 0 < size <= maximum)
        total += size
        require(total <= 1073741824)
        _hash(record["sha256"])
        payload = files[path]
        require(type(payload) is bytes and len(payload) == size)
        require(sha256(payload).hexdigest() == record["sha256"])
        verified[path] = payload
    require(type(m["total_mb"]) in (int, float) and m["total_mb"] == round(total / 1e6, 1))
    return VerifiedPack(m["version"], expected_sha256, manifest, MappingProxyType(verified))


def verify_pack(manifest, files, *, expected_sha256):
    try:
        return _verify(manifest, files, expected_sha256)
    except ModelInputError:
        raise
    except Exception:
        raise ModelInputError("model_unavailable") from None
