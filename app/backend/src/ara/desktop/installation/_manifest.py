"""Closed portable manifest decoder, independently pinned by its caller."""

import json
import re
from hashlib import sha256
from types import MappingProxyType

from ._models import FileRecord, InstallationManifest, PackageError, require

NAME = "aira-installation.json"
MAX_MANIFEST = 4 * 1024 * 1024
TARGETS = frozenset({"macos-arm64", "macos-x86_64", "windows-x86_64"})
EXECUTABLE = frozenset({"python", "postgres", "initdb", "pg_dump", "pg_restore", "pg_controldata"})
ROLES = EXECUTABLE | {"application", "frontend", "model_manifest"}
RESERVED = {"con", "prn", "aux", "nul"} | {f"{p}{n}" for p in ("com", "lpt") for n in range(1, 10)}


def digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def arguments(expected_sha256, target, allow_fixture):
    require(
        digest(expected_sha256)
        and type(target) is str
        and target in TARGETS
        and type(allow_fixture) is bool,
        "validation_error",
    )


def _path(value):
    require(type(value) is str and 0 < len(value) <= 1024)
    parts = value.split("/")
    require(len(parts) <= 32 and value.lower() != NAME)
    for part in parts:
        require(
            re.fullmatch(r"[A-Za-z0-9_.+-]{1,180}", part) is not None
            and part not in {".", ".."}
            and not part.endswith(".")
            and part.split(".")[0].lower() not in RESERVED
        )


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result)
        result[k] = v
    return result


def _constant(_):
    raise PackageError()


def _json(raw):
    text = raw.decode("utf-8")
    inside = escaped = False
    depth = 0
    for char in text:
        if inside:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                inside = False
        elif char == '"':
            inside = True
        elif char in "[{":
            depth += 1
            require(depth <= 8)
        elif char in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)


def _parse(raw, expected_sha256, target, allow_fixture):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST)
    require(sha256(raw).hexdigest() == expected_sha256, "package_mismatch")
    m = _json(raw)
    require(
        type(m) is dict
        and set(m)
        == {
            "schema_version",
            "product",
            "version",
            "target",
            "kind",
            "files",
            "entrypoints",
            "model_manifest_sha256",
        }
    )
    require(m["schema_version"] == "aira-installation/1" and m["product"] == "aira")
    require(
        type(m["version"]) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", m["version"]) is not None
    )
    require(m["target"] == target, "unsupported_target")
    require(m["kind"] in {"production", "fixture"})
    require(m["kind"] != "fixture" or allow_fixture, "fixture_not_allowed")
    require(type(m["files"]) is list and 1 <= len(m["files"]) <= 32768)
    records, nodes, files, total = [], {}, set(), 0
    for item in m["files"]:
        require(type(item) is dict and set(item) == {"path", "bytes", "sha256", "executable"})
        path, size = item["path"], item["bytes"]
        _path(path)
        require(
            type(size) is int
            and 0 <= size <= 8 * 1024**3
            and digest(item["sha256"])
            and type(item["executable"]) is bool
        )
        total += size
        require(total <= 16 * 1024**3 and path.lower() not in nodes)
        parts = path.split("/")
        for end in range(1, len(parts)):
            parent = "/".join(parts[:end])
            key = parent.lower()
            require(key not in files and (key not in nodes or nodes[key] == parent))
            nodes[key] = parent
        nodes[path.lower()] = path
        files.add(path.lower())
        records.append(FileRecord(path, size, item["sha256"], item["executable"]))
    require([r.path for r in records] == sorted(r.path for r in records))
    roles = m["entrypoints"]
    require(type(roles) is dict and set(roles) == ROLES)
    indexed, used = {r.path: r for r in records}, set()
    for role, path in roles.items():
        if role == "model_manifest" and m["kind"] == "fixture":
            require(path is None and m["model_manifest_sha256"] is None)
            continue
        require(type(path) is str and path in indexed and path not in used)
        record = indexed[path]
        require(record.size > 0 and record.executable == (role in EXECUTABLE))
        used.add(path)
    if m["kind"] == "production":
        require(
            digest(m["model_manifest_sha256"])
            and indexed[roles["model_manifest"]].sha256 == m["model_manifest_sha256"]
        )
    return InstallationManifest(
        m["version"],
        target,
        m["kind"],
        expected_sha256,
        tuple(records),
        MappingProxyType(dict(roles)),
        m["model_manifest_sha256"],
        total,
    )


def parse_manifest(raw, *, expected_sha256, target, allow_fixture=False):
    arguments(expected_sha256, target, allow_fixture)
    try:
        return _parse(raw, expected_sha256, target, allow_fixture)
    except PackageError:
        raise
    except Exception:
        raise PackageError() from None
