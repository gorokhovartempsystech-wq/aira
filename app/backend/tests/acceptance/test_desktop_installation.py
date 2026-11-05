"""Independent payload manifest tests: all executable/model bytes are synthetic."""

import copy
import importlib
import json
import os
from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

TARGET = "macos-arm64"
EXECUTABLE = {"python", "postgres", "initdb", "pg_dump", "pg_restore", "pg_controldata"}


def api():
    return importlib.import_module("ara.desktop.installation")


def sample(*, fixture=False):
    entries = dict(
        python="runtime/python",
        application="app/main.py",
        postgres="pg/postgres",
        initdb="pg/initdb",
        pg_dump="pg/pg_dump",
        pg_restore="pg/pg_restore",
        pg_controldata="pg/pg_controldata",
        frontend="frontend/index.html",
        model_manifest=None if fixture else "model/manifest.json",
    )
    files = {path: ("SYNTHETIC-" + role).encode() for role, path in entries.items() if path}
    manifest = dict(
        schema_version="aira-installation/1",
        product="aira",
        version="0.1.0-test",
        target=TARGET,
        kind="fixture" if fixture else "production",
        files=[],
        entrypoints=entries,
        model_manifest_sha256=None if fixture else sha256(files["model/manifest.json"]).hexdigest(),
    )
    for role, path in entries.items():
        if path:
            manifest["files"].append(
                dict(
                    path=path,
                    bytes=len(files[path]),
                    sha256=sha256(files[path]).hexdigest(),
                    executable=role in EXECUTABLE,
                )
            )
    manifest["files"].sort(key=lambda r: r["path"])
    return manifest, files


def encoded(manifest):
    return json.dumps(manifest, separators=(",", ":"), ensure_ascii=True).encode()


def parse(manifest, **kwargs):
    raw = encoded(manifest)
    options = dict(expected_sha256=sha256(raw).hexdigest(), target=TARGET)
    options.update(kwargs)
    return api().parse_manifest(raw, **options)


def reject(code, call):
    with pytest.raises(api().PackageError) as error:
        call()
    assert error.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(error.value) + repr(error.value)


def test_manifest_is_pure_detached_and_not_executable_authority(monkeypatch):
    m, files = sample()
    module = api()

    def forbidden(*args, **kwargs):
        raise AssertionError("Pure decoder attempted I/O")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", forbidden)
        value = parse(m)
    assert type(value) is module.InstallationManifest
    assert value.version == m["version"] and value.target == TARGET and value.kind == "production"
    assert value.sha256 == sha256(encoded(m)).hexdigest()
    assert value.total_bytes == sum(map(len, files.values()))
    assert tuple(r.path for r in value.files) == tuple(sorted(files))
    assert dict(value.entrypoints) == m["entrypoints"]
    assert value.model_manifest_sha256 == m["model_manifest_sha256"]
    m["entrypoints"]["python"] = "changed"
    assert value.entrypoints["python"] == "runtime/python"
    with pytest.raises(TypeError):
        value.entrypoints["python"] = "changed"
    with pytest.raises(FrozenInstanceError):
        value.kind = "production"
    for record in value.files:
        assert record.path not in repr(record) + repr(value)
        assert record.sha256 not in repr(record) + repr(value)


def test_fixture_requires_explicit_permission_and_keeps_identity():
    m, _ = sample(fixture=True)
    reject("fixture_not_allowed", lambda: parse(m))
    result = parse(m, allow_fixture=True)
    assert result.kind == "fixture" and result.model_manifest_sha256 is None
    assert result.entrypoints["model_manifest"] is None


def test_expected_manifest_pin_and_target_are_checked():
    m, _ = sample()
    reject("package_mismatch", lambda: parse(m, expected_sha256="0" * 64))
    reject("unsupported_target", lambda: parse(m, target="windows-x86_64"))


@pytest.mark.parametrize(
    "options",
    [
        {"target": "linux-x86_64"},
        {"target": None},
        {"allow_fixture": 1},
        {"expected_sha256": "A" * 64},
        {"expected_sha256": b"0" * 64},
    ],
)
def test_public_argument_types(options):
    m, _ = sample()
    reject("validation_error", lambda: parse(m, **options))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"null",
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b"[" * 9 + b"]" * 9,
        b"x" * (4 * 1024 * 1024 + 1),
    ],
)
def test_invalid_json_is_bounded_and_sanitized(raw):
    reject(
        "package_invalid",
        lambda: api().parse_manifest(raw, expected_sha256=sha256(raw).hexdigest(), target=TARGET),
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(extra=True),
        lambda m: m.update(product="other"),
        lambda m: m.update(schema_version="aira-installation/2"),
        lambda m: m.update(version="SYNTHETIC_PRIVATE\n"),
        lambda m: m.update(kind="demo"),
        lambda m: m.update(files=[]),
        lambda m: m["files"].reverse(),
        lambda m: m["files"][0].update(bytes=True),
        lambda m: m["files"][0].update(bytes=-1),
        lambda m: m["files"][0].update(bytes=8 * 1024**3 + 1),
        lambda m: m["files"][0].update(sha256="F" * 64),
        lambda m: m["files"][0].update(executable=1),
        lambda m: m["entrypoints"].update(extra="app/main.py"),
        lambda m: m["entrypoints"].update(python="absent"),
        lambda m: m["entrypoints"].update(frontend="app/main.py"),
        lambda m: m.update(model_manifest_sha256="0" * 64),
        lambda m: m["entrypoints"].update(model_manifest=None),
    ],
)
def test_closed_shape_roles_and_bounds(mutation):
    m, _ = sample()
    mutation(m)
    reject("package_invalid", lambda: parse(m))


@pytest.mark.parametrize(
    "path",
    [
        "/absolute",
        "../escape",
        "a/../escape",
        "a//b",
        "a/./b",
        "a\\b",
        "C:/a",
        "a:",
        "a.",
        "CON.txt",
        "x/COM1",
        "x/lpt9.onnx",
        "a\x00b",
        "юникод",
        "x" * 181,
        "a/" * 32 + "b",
        "AIRA-INSTALLATION.JSON",
    ],
)
def test_paths_have_one_portable_interpretation(path):
    m, _ = sample()
    record = copy.deepcopy(m["files"][0])
    record["path"] = path
    m["files"].append(record)
    m["files"].sort(key=lambda r: r["path"])
    reject("package_invalid", lambda: parse(m))


@pytest.mark.parametrize(
    "paths",
    [
        ["app/main.py"],
        ["APP/other.py"],
        ["app"],
        ["app/main.py/child"],
        ["extra/A", "extra/a"],
        ["one/X/file", "one/x/other"],
    ],
)
def test_file_and_directory_aliases_rejected(paths):
    m, _ = sample()
    for path in paths:
        record = copy.deepcopy(m["files"][0])
        record["path"] = path
        m["files"].append(record)
    m["files"].sort(key=lambda r: r["path"])
    reject("package_invalid", lambda: parse(m))


def test_total_bytes_limit_and_required_nonempty_executable_roles():
    for mutation in ("total", "empty", "mode"):
        m, _ = sample()
        if mutation == "total":
            for r in m["files"][:3]:
                r["bytes"] = 8 * 1024**3
        else:
            record = next(r for r in m["files"] if r["path"] == m["entrypoints"]["python"])
            record["bytes" if mutation == "empty" else "executable"] = (
                0 if mutation == "empty" else False
            )
        reject("package_invalid", lambda: parse(m))
