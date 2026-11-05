"""Additional inventory integration and mutation review without real model assets."""

import importlib
import os
from hashlib import sha256

import pytest
from test_desktop_installation import TARGET, api, encoded, reject, sample
from test_desktop_installation_files import payload as payload
from test_desktop_installation_files import verify


def repin(w):
    raw = encoded(w["manifest"])
    (w["root"] / "aira-installation.json").write_bytes(raw)
    w["pin"] = sha256(raw).hexdigest()


def test_large_file_streamed_in_chunks_and_empty_auxiliary_file_supported(payload, monkeypatch):
    w = payload
    data = b"a" * (2 * 1024 * 1024 + 17)
    (w["root"] / "large.bin").write_bytes(data)
    (w["root"] / "empty").write_bytes(b"")
    for path, content in (("large.bin", data), ("empty", b"")):
        w["manifest"]["files"].append(
            dict(
                path=path, bytes=len(content), sha256=sha256(content).hexdigest(), executable=False
            )
        )
    w["manifest"]["files"].sort(key=lambda r: r["path"])
    repin(w)
    read, chunks = os.read, []

    def observed(fd, size):
        assert size <= 1024 * 1024
        value = read(fd, size)
        if os.fstat(fd).st_size == len(data):
            chunks.append(len(value))
        return value

    monkeypatch.setattr(os, "read", observed)
    assert verify(w).manifest.total_bytes == sum(r["bytes"] for r in w["manifest"]["files"])
    assert chunks == [1024 * 1024, 1024 * 1024, 17, 0]


def test_final_inventory_detects_change_to_already_hashed_file(payload, monkeypatch):
    w = payload
    read = os.read
    mutated = False

    def observed(fd, size):
        nonlocal mutated
        data = read(fd, size)
        if data.startswith(b"SYNTHETIC-python") and not mutated:
            mutated = True
            (w["root"] / "app/main.py").write_bytes(b"changed")
        return data

    monkeypatch.setattr(os, "read", observed)
    reject("package_invalid", lambda: verify(w))
    assert mutated


def test_unexpected_file_content_is_never_read(payload, monkeypatch):
    w = payload
    (w["root"] / "unlisted").write_bytes(b"DO_NOT_READ_SYNTHETIC")
    original = os.read

    def observed(fd, size):
        data = original(fd, size)
        assert b"DO_NOT_READ_SYNTHETIC" not in data
        return data

    monkeypatch.setattr(os, "read", observed)
    reject("package_invalid", lambda: verify(w))


def test_observed_reparse_metadata_rejected_on_every_platform(payload, monkeypatch):
    w = payload
    module = importlib.import_module("ara.desktop.installation._files")
    original = module.Tree.info

    class Reparse:
        st_file_attributes = 0x400

        def __init__(self, info):
            self.info = info

        def __getattr__(self, name):
            return getattr(self.info, name)

    def info(tree, parent, name, fd):
        value = original(tree, parent, name, fd)
        return Reparse(value) if name == "frontend" else value

    monkeypatch.setattr(module.Tree, "info", info)
    reject("package_invalid", lambda: verify(w))


def test_fixture_files_require_opt_in_and_missing_role_has_no_path(tmp_path):
    m, files = sample(fixture=True)
    for record in m["files"]:
        path = tmp_path / record["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[record["path"]])
        path.chmod(0o755 if record["executable"] else 0o644)
    raw = encoded(m)
    (tmp_path / "aira-installation.json").write_bytes(raw)
    args = dict(expected_sha256=sha256(raw).hexdigest(), target=TARGET)
    reject("fixture_not_allowed", lambda: api().verify_installation(tmp_path, **args))
    result = api().verify_installation(tmp_path, **args, allow_fixture=True)
    assert result.manifest.kind == "fixture"
    reject("validation_error", lambda: result.role_path("model_manifest"))


def test_windows_target_can_be_preflighted_without_posix_executable_bits(payload):
    w = payload
    w["manifest"]["target"] = "windows-x86_64"
    for record in w["manifest"]["files"]:
        (w["root"] / record["path"]).chmod(0o644)
    repin(w)
    result = api().verify_installation(w["root"], expected_sha256=w["pin"], target="windows-x86_64")
    assert result.manifest.target == "windows-x86_64"


@pytest.mark.parametrize("issue", ["missing", "permission"])
def test_unavailable_manifest_uses_fixed_errors(payload, monkeypatch, issue):
    w = payload
    if issue == "missing":
        (w["root"] / "aira-installation.json").unlink()
    else:

        def denied(*args, **kwargs):
            raise PermissionError("SYNTHETIC_PRIVATE")

        monkeypatch.setattr(os, "open", denied)
    reject("package_unavailable", lambda: verify(w))
