"""Read-only installation preflight against disposable synthetic payloads."""

import os
import stat
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from test_desktop_installation import TARGET, api, encoded, reject, sample


@pytest.fixture
def payload(tmp_path):
    root = tmp_path / "SYNTHETIC_PRIVATE"
    root.mkdir()
    manifest, files = sample()
    for record in manifest["files"]:
        path = root / record["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[record["path"]])
        path.chmod(0o755 if record["executable"] else 0o644)
    raw = encoded(manifest)
    (root / "aira-installation.json").write_bytes(raw)
    return dict(root=root, manifest=manifest, raw=raw, pin=sha256(raw).hexdigest(), files=files)


def verify(w):
    return api().verify_installation(w["root"], expected_sha256=w["pin"], target=TARGET)


def test_verify_exact_tree_readonly_and_role_paths(payload):
    w = payload
    before = {
        str(p.relative_to(w["root"])): p.read_bytes() for p in w["root"].rglob("*") if p.is_file()
    }
    result = verify(w)
    assert result.manifest.total_bytes == sum(map(len, w["files"].values()))
    assert result.role_path("postgres") == w["root"] / "pg/postgres"
    assert "SYNTHETIC_PRIVATE" not in repr(result)
    reject("validation_error", lambda: result.role_path("SYNTHETIC_PRIVATE"))
    after = {
        str(p.relative_to(w["root"])): p.read_bytes() for p in w["root"].rglob("*") if p.is_file()
    }
    assert before == after


@pytest.mark.parametrize(
    "kind,code",
    [
        ("missing", "package_unavailable"),
        ("changed", "package_mismatch"),
        ("short", "package_mismatch"),
        ("long", "package_mismatch"),
        ("extra", "package_invalid"),
        ("empty_dir", "package_invalid"),
        ("manifest", "package_mismatch"),
    ],
)
def test_broken_payload_never_verifies(payload, kind, code):
    w = payload
    path = w["root"] / "frontend/index.html"
    if kind == "missing":
        path.unlink()
    elif kind == "changed":
        path.write_bytes(b"x" * path.stat().st_size)
    elif kind == "short":
        path.write_bytes(b"x")
    elif kind == "long":
        path.write_bytes(path.read_bytes() + b"x")
    elif kind == "extra":
        (w["root"] / "extra").write_bytes(b"SYNTHETIC_PRIVATE")
    elif kind == "empty_dir":
        (w["root"] / "extra").mkdir()
    else:
        (w["root"] / "aira-installation.json").write_bytes(b"{}")
    reject(code, lambda: verify(w))


@pytest.mark.parametrize("kind", ["file_link", "directory_link", "root_link", "hardlink", "fifo"])
def test_links_and_special_files_are_not_read(payload, kind):
    w = payload
    target = w["root"] / "frontend/index.html"
    if kind == "fifo" and os.name != "posix":
        pytest.skip("POSIX FIFO boundary")
    if kind == "root_link":
        link = w["root"].parent / "alias"
        link.symlink_to(w["root"], target_is_directory=True)
        w["root"] = link
    elif kind == "directory_link":
        directory = w["root"] / "frontend"
        outside = w["root"].parent / "outside"
        directory.rename(outside)
        directory.symlink_to(outside, target_is_directory=True)
    else:
        data = target.read_bytes()
        target.unlink()
        outside = w["root"].parent / "outside"
        outside.write_bytes(data)
        if kind == "file_link":
            target.symlink_to(outside)
        elif kind == "hardlink":
            os.link(outside, target)
        else:
            os.mkfifo(target)
    reject("package_invalid", lambda: verify(w))


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable mode")
def test_required_binary_must_have_executable_bit(payload):
    w = payload
    (w["root"] / "runtime/python").chmod(0o644)
    reject("package_invalid", lambda: verify(w))


@pytest.mark.parametrize("root", [Path("relative"), Path("/a/../b"), "SYNTHETIC_PRIVATE"])
def test_invalid_root_does_not_access_files(root):
    reject(
        "validation_error",
        lambda: api().verify_installation(root, expected_sha256="0" * 64, target=TARGET),
    )


def test_streaming_is_bounded_and_observed_change_rejected(payload, monkeypatch):
    w = payload
    module = api()
    original = os.read
    changed = False

    def read(fd, size):
        nonlocal changed
        assert size <= 1024 * 1024
        data = original(fd, size)
        if data.startswith(b"SYNTHETIC-frontend") and not changed:
            changed = True
            with (w["root"] / "frontend/index.html").open("ab") as file:
                file.write(b"changed")
        return data

    monkeypatch.setattr(os, "read", read)
    reject("package_invalid", lambda: verify(w))
    assert changed and module is api()


def test_special_file_metadata_is_admitted_before_content_read(payload, monkeypatch):
    w = payload
    if os.name != "posix":
        pytest.skip("POSIX FIFO boundary")
    path = w["root"] / "frontend/index.html"
    path.unlink()
    os.mkfifo(path)
    real_read = os.read

    def guarded(fd, size):
        assert not stat.S_ISFIFO(os.fstat(fd).st_mode)
        return real_read(fd, size)

    monkeypatch.setattr(os, "read", guarded)
    reject("package_invalid", lambda: verify(w))


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows installation payload gate")
def test_native_windows_payload(payload):
    w = payload
    w["manifest"]["target"] = "windows-x86_64"
    raw = encoded(w["manifest"])
    (w["root"] / "aira-installation.json").write_bytes(raw)
    result = api().verify_installation(
        w["root"], expected_sha256=sha256(raw).hexdigest(), target="windows-x86_64"
    )
    assert result.manifest.target == "windows-x86_64"
