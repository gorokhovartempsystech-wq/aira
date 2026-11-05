"""Offline assembly from synthetic staged bytes; nothing here is an executable/model."""

import importlib
import os
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest
from test_desktop_installation import sample


def api():
    return importlib.import_module("ara.desktop.build")


def staged(tmp_path, *, fixture=True, target="macos-arm64"):
    manifest, files = sample(fixture=fixture)
    files.update(
        {
            "runtime/lib/stdlib.zip": b"SYNTHETIC-STDLIB",
            "licenses/NOTICE.txt": b"Synthetic license",
            "app/empty.dat": b"",
        }
    )
    source = tmp_path / "SYNTHETIC_PRIVATE_SOURCE"
    source.mkdir()
    for name, data in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o600)
    options = dict(
        version="0.1.0-test",
        target=target,
        kind="fixture" if fixture else "production",
        entrypoints=manifest["entrypoints"],
    )
    return source, files, options


def reject(code, call):
    with pytest.raises(api().BuildError) as error:
        call()
    assert error.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(error.value) + repr(error.value)


def verify(receipt, target, fixture=True):
    from ara.desktop.installation import verify_installation

    verified = verify_installation(
        receipt.installation.root,
        expected_sha256=receipt.manifest_sha256,
        target=target,
        allow_fixture=fixture,
    )
    assert verified == receipt.installation
    assert sha256(receipt.manifest_bytes).hexdigest() == receipt.manifest_sha256
    assert (verified.root / "aira-installation.json").read_bytes() == receipt.manifest_bytes
    return verified


@pytest.mark.parametrize("target", ["macos-arm64", "macos-x86_64", "windows-x86_64"])
@pytest.mark.parametrize("fixture", [True, False])
def test_full_inventory_byte_copy_closed_profile_and_output_pin(tmp_path, target, fixture):
    source, files, options = staged(tmp_path, fixture=fixture, target=target)
    before = {
        name: ((source / name).stat().st_mtime_ns, (source / name).stat().st_ino) for name in files
    }
    destination = tmp_path / "payload"
    receipt = api().build_payload(source, destination, **options)
    verified = verify(receipt, target, fixture)
    assert verified.manifest.kind == options["kind"]
    assert verified.manifest.total_bytes == sum(map(len, files.values()))
    assert [r.path for r in verified.manifest.files] == sorted(files)
    assert dict(verified.manifest.entrypoints) == options["entrypoints"]
    for record in verified.manifest.files:
        assert (destination / record.path).read_bytes() == files[record.path]
        assert (source / record.path).read_bytes() == files[record.path]
        assert (
            (source / record.path).stat().st_mtime_ns,
            (source / record.path).stat().st_ino,
        ) == before[record.path]
        if os.name == "posix":
            assert bool((destination / record.path).stat().st_mode & 0o111) == record.executable
    assert "SYNTHETIC_PRIVATE" not in repr(receipt)
    with pytest.raises(FrozenInstanceError):
        receipt.manifest_sha256 = "0" * 64
    if fixture:
        from ara.desktop.installation import PackageError, verify_installation

        with pytest.raises(PackageError) as error:
            verify_installation(destination, expected_sha256=receipt.manifest_sha256, target=target)
        assert error.value.code == "fixture_not_allowed"


def test_determinism_executable_declaration_and_independent_copies(tmp_path):
    source, files, options = staged(tmp_path)
    helper = "runtime/helper"
    (source / helper).write_bytes(b"SYNTHETIC-HELPER")
    options["extra_executables"] = (helper,)
    first = api().build_payload(source, tmp_path / "first", **options)
    os.utime(source / "app/main.py", (123456, 123456))
    second = api().build_payload(source, tmp_path / "second", **options)
    assert first.manifest_bytes == second.manifest_bytes
    assert first.manifest_sha256 == second.manifest_sha256
    assert next(r for r in first.installation.manifest.files if r.path == helper).executable
    for name in files:
        assert (source / name).stat().st_ino != (tmp_path / "first" / name).stat().st_ino
    (source / "app/main.py").write_bytes(b"CHANGED-SYNTHETIC")
    assert (tmp_path / "first/app/main.py").read_bytes() == files["app/main.py"]


@pytest.mark.parametrize(
    "change",
    [
        {"version": "bad version"},
        {"version": None},
        {"target": "linux-x86_64"},
        {"target": []},
        {"kind": "demo"},
        {"kind": True},
        {"entrypoints": []},
        {"extra_executables": ["runtime/python"]},
        {"extra_executables": ("../escape",)},
        {"extra_executables": ("runtime/python", "runtime/python")},
    ],
)
def test_invalid_public_inputs_never_create_output(tmp_path, change):
    source, _, options = staged(tmp_path)
    options.update(change)
    output = tmp_path / "payload"
    reject("validation_error", lambda: api().build_payload(source, output, **options))
    assert not output.exists()


@pytest.mark.parametrize(
    "fault", ["missing_role", "duplicate_role", "absent_file", "absent_model", "unknown_extra"]
)
def test_invalid_payload_roles_never_create_output(tmp_path, fault):
    source, _, options = staged(tmp_path, fixture=fault != "absent_model")
    if fault == "missing_role":
        del options["entrypoints"]["python"]
    elif fault == "duplicate_role":
        options["entrypoints"]["frontend"] = options["entrypoints"]["application"]
    elif fault == "absent_file":
        (source / options["entrypoints"]["postgres"]).unlink()
    elif fault == "absent_model":
        (source / options["entrypoints"]["model_manifest"]).unlink()
    else:
        options["extra_executables"] = ("absent",)
    output = tmp_path / "payload"
    reject(
        "validation_error" if fault == "missing_role" else "source_invalid",
        lambda: api().build_payload(source, output, **options),
    )
    assert not output.exists()


@pytest.mark.parametrize("kind", ["directory", "empty_directory", "file", "link"])
def test_existing_destination_is_never_changed(tmp_path, kind):
    source, _, options = staged(tmp_path)
    output = tmp_path / "payload"
    outside = tmp_path / "outside"
    outside.write_bytes(b"SYNTHETIC-KEEP")
    if kind == "directory":
        output.mkdir()
        (output / "keep").write_bytes(b"SYNTHETIC-KEEP")
    elif kind == "empty_directory":
        output.mkdir()
    elif kind == "file":
        output.write_bytes(b"SYNTHETIC-KEEP")
    else:
        output.symlink_to(outside)
    reject("destination_exists", lambda: api().build_payload(source, output, **options))
    assert outside.read_bytes() == b"SYNTHETIC-KEEP"
    if kind == "empty_directory":
        assert output.is_dir() and list(output.iterdir()) == []
    else:
        assert (
            (output / "keep").read_bytes() == b"SYNTHETIC-KEEP"
            if kind == "directory"
            else output.read_bytes() == b"SYNTHETIC-KEEP"
        )


@pytest.mark.parametrize("case", ["same", "child", "relative", "dotdot"])
def test_overlap_and_noncanonical_paths_do_not_touch_source(tmp_path, case):
    source, files, options = staged(tmp_path)
    output = source if case == "same" else source / "payload"
    if case == "relative":
        source = Path("relative")
        output = tmp_path / "payload"
    elif case == "dotdot":
        source = source / ".." / source.name
    reject("validation_error", lambda: api().build_payload(source, output, **options))
    assert (tmp_path / "SYNTHETIC_PRIVATE_SOURCE/app/main.py").read_bytes() == files["app/main.py"]
    assert not (tmp_path / "SYNTHETIC_PRIVATE_SOURCE/payload").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "file_link",
        "directory_link",
        "hardlink",
        "fifo",
        "empty_directory",
        "manifest",
        "wrong_case_role",
        "invalid_name",
    ],
)
def test_source_shape_rejection_is_read_only(tmp_path, fault):
    source, files, options = staged(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"SYNTHETIC-OUTSIDE")
    if fault == "file_link":
        (source / "bad").symlink_to(outside)
    elif fault == "directory_link":
        (source / "bad").symlink_to(source / "app", target_is_directory=True)
    elif fault == "hardlink":
        os.link(source / "app/main.py", source / "bad")
    elif fault == "fifo":
        if not hasattr(os, "mkfifo"):
            pytest.skip("POSIX FIFO")
        os.mkfifo(source / "bad")
    elif fault == "empty_directory":
        (source / "bad").mkdir()
    elif fault == "manifest":
        (source / "aira-installation.json").write_bytes(b"SYNTHETIC-OLD-MANIFEST")
    elif fault == "wrong_case_role":
        # Roles must use exact inventoried spelling even on case-insensitive hosts.
        options["entrypoints"]["frontend"] = "App/main.py"
    else:
        (source / "bad name").write_bytes(b"SYNTHETIC")
    output = tmp_path / "payload"
    reject("source_invalid", lambda: api().build_payload(source, output, **options))
    assert not output.exists() and outside.read_bytes() == b"SYNTHETIC-OUTSIDE"
    assert all((source / name).read_bytes() == data for name, data in files.items())


def test_sparse_oversize_is_rejected_before_copy_or_destination(tmp_path):
    source, _, options = staged(tmp_path)
    with (source / "too-large").open("wb") as stream:
        stream.truncate(8 * 1024**3 + 1)
    output = tmp_path / "payload"
    reject("source_invalid", lambda: api().build_payload(source, output, **options))
    assert not output.exists()


def test_copy_is_streamed_and_handles_short_writes(tmp_path, monkeypatch):
    source, files, options = staged(tmp_path)
    data = b"SYNTHETIC-LARGE" * 200000
    (source / "runtime/large.bin").write_bytes(data)
    original_read, original_write = os.read, os.write
    reads, writes = [], []

    def read(fd, count):
        assert 0 < count <= 1024 * 1024
        reads.append(count)
        return original_read(fd, count)

    def write(fd, block):
        assert len(block) <= 1024 * 1024
        writes.append(len(block))
        return original_write(fd, block[:4096])

    monkeypatch.setattr(os, "read", read)
    monkeypatch.setattr(os, "write", write)
    receipt = api().build_payload(source, tmp_path / "payload", **options)
    verify(receipt, options["target"])
    assert (receipt.installation.root / "runtime/large.bin").read_bytes() == data
    assert len(reads) > len(files) and len(writes) > 10


@pytest.mark.parametrize("fault", ["modify", "add_file"])
def test_observed_source_change_cannot_return_a_receipt(tmp_path, monkeypatch, fault):
    source, files, options = staged(tmp_path)
    target = source / "runtime/python"
    inode = target.stat().st_ino
    original = os.read
    changed = False

    def read(fd, count):
        nonlocal changed
        data = original(fd, count)
        if os.fstat(fd).st_ino == inode and data and not changed:
            changed = True
            if fault == "modify":
                target.write_bytes(b"CHANGED-SYNTHETIC")
            else:
                (source / "added-after-scan").write_bytes(b"SYNTHETIC")
        return data

    monkeypatch.setattr(os, "read", read)
    destination = tmp_path / "payload"
    reject("source_changed", lambda: api().build_payload(source, destination, **options))
    assert changed and destination.is_dir()
    assert not (destination / "aira-installation.json").exists()
    assert (source / "app/main.py").read_bytes() == files["app/main.py"]


@pytest.mark.parametrize("fault", ["zero_write", "disk_full"])
def test_failed_copy_retains_private_partial_output_and_never_changes_source(
    tmp_path, monkeypatch, fault
):
    import errno

    source, files, options = staged(tmp_path)
    destination = tmp_path / "payload"
    outside = tmp_path / "unrelated"
    outside.write_bytes(b"SYNTHETIC-KEEP")

    def write(*args):
        if fault == "zero_write":
            return 0
        raise OSError(errno.ENOSPC, "SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", write)
        reject("build_failed", lambda: api().build_payload(source, destination, **options))
    assert destination.is_dir() and not (destination / "aira-installation.json").exists()
    assert all((source / name).read_bytes() == data for name, data in files.items())
    assert outside.read_bytes() == b"SYNTHETIC-KEEP"
    reject("destination_exists", lambda: api().build_payload(source, destination, **options))
    verify(api().build_payload(source, tmp_path / "fresh", **options), options["target"])


def test_final_verifier_rejects_unlisted_output_without_deleting_it(tmp_path, monkeypatch):
    source, files, options = staged(tmp_path)
    module = importlib.import_module("ara.desktop.build._build")
    original = module.verify_installation

    def verify_with_added_file(root, **kwargs):
        (root / "unrelated").write_bytes(b"SYNTHETIC-KEEP")
        return original(root, **kwargs)

    monkeypatch.setattr(module, "verify_installation", verify_with_added_file)
    output = tmp_path / "payload"
    reject("build_failed", lambda: api().build_payload(source, output, **options))
    assert (output / "unrelated").read_bytes() == b"SYNTHETIC-KEEP"
    assert all((source / name).read_bytes() == data for name, data in files.items())


def test_missing_source_or_destination_parent_is_safe_and_fixed_error(tmp_path):
    source, files, options = staged(tmp_path)
    reject(
        "source_unavailable",
        lambda: api().build_payload(tmp_path / "absent", tmp_path / "payload", **options),
    )
    reject(
        "destination_unavailable",
        lambda: api().build_payload(source, tmp_path / "absent/payload", **options),
    )
    assert not (tmp_path / "absent").exists() and not (tmp_path / "payload").exists()
    assert all((source / name).read_bytes() == data for name, data in files.items())


def test_real_overlap_through_parent_alias_is_rejected_before_writes(tmp_path):
    source, files, options = staged(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    reject("validation_error", lambda: api().build_payload(source, alias / "payload", **options))
    assert not (source / "payload").exists()
    assert all((source / name).read_bytes() == data for name, data in files.items())


def test_module_import_has_no_runtime_filesystem_network_process_or_environment_work(tmp_path):
    import subprocess
    import sys

    script = r"""
import importlib, os, pathlib, socket, subprocess, sys
sys.path.insert(0, str(pathlib.Path.cwd() / "src"))
def forbidden(*args, **kwargs):
    raise AssertionError("Import performed runtime I/O")
for owner, names in ((os, ("open", "scandir", "getenv")),
                     (pathlib.Path, ("open", "read_bytes", "write_bytes", "mkdir")),
                     (socket, ("socket", "create_connection")),
                     (subprocess, ("Popen", "run"))):
    for name in names:
        setattr(owner, name, forbidden)
module = importlib.import_module("ara.desktop.build")
assert callable(module.build_payload)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == b"" and result.stderr == b""


def cli(source, destination, options, roles):
    import subprocess
    import sys

    script = (
        'import pathlib,runpy,sys;sys.path.insert(0,str(pathlib.Path.cwd()/"src"));'
        'runpy.run_module("ara.desktop.build",run_name="__main__")'
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--version",
            options["version"],
            "--target",
            options["target"],
            "--kind",
            options["kind"],
            "--roles",
            str(roles),
        ],
        capture_output=True,
        timeout=20,
    )


def test_cli_returns_only_content_pin_and_summary_and_never_executes_payload(tmp_path):
    import json

    source, files, options = staged(tmp_path)
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps(options["entrypoints"]))
    output = tmp_path / "payload"
    result = cli(source, output, options, roles)
    assert result.returncode == 0 and result.stderr == b"", result.stderr.decode()
    summary = json.loads(result.stdout)
    assert set(summary) == {"manifest_sha256", "version", "target", "kind", "files", "bytes"}
    assert summary["kind"] == "fixture" and summary["target"] == options["target"]
    assert summary["files"] == len(files) and summary["bytes"] == sum(map(len, files.values()))
    assert (
        summary["manifest_sha256"]
        == sha256((output / "aira-installation.json").read_bytes()).hexdigest()
    )
    assert "SYNTHETIC_PRIVATE" not in result.stdout.decode()


@pytest.mark.parametrize("fault", ["duplicate_roles", "oversize_roles", "existing_output"])
def test_cli_failure_is_content_safe_and_does_not_overwrite(tmp_path, fault):
    import json

    source, _, options = staged(tmp_path)
    roles = tmp_path / "SYNTHETIC_PRIVATE_ROLES.json"
    roles.write_text(json.dumps(options["entrypoints"]))
    output = tmp_path / "payload"
    if fault == "duplicate_roles":
        roles.write_text('{"python":"SYNTHETIC_PRIVATE","python":"other"}')
    elif fault == "oversize_roles":
        roles.write_bytes(b" " * 65537)
    else:
        output.mkdir()
        (output / "keep").write_bytes(b"SYNTHETIC-KEEP")
    result = cli(source, output, options, roles)
    assert result.returncode == (1 if fault == "existing_output" else 2)
    assert result.stdout == b""
    assert json.loads(result.stderr) == {
        "code": "destination_exists" if fault == "existing_output" else "validation_error"
    }
    assert "SYNTHETIC_PRIVATE" not in result.stderr.decode()
    if fault == "existing_output":
        assert (output / "keep").read_bytes() == b"SYNTHETIC-KEEP"
    else:
        assert not output.exists()


def test_source_root_link_is_not_adopted(tmp_path):
    source, files, options = staged(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(source, target_is_directory=True)
    output = tmp_path / "payload"
    reject("source_invalid", lambda: api().build_payload(alias, output, **options))
    assert not output.exists() and alias.is_symlink()
    assert all((source / name).read_bytes() == data for name, data in files.items())


def test_source_is_revalidated_even_after_successful_output_verification(tmp_path, monkeypatch):
    source, files, options = staged(tmp_path)
    module = importlib.import_module("ara.desktop.build._build")
    original = module.verify_installation

    def changed_source(root, **kwargs):
        verified = original(root, **kwargs)
        (source / "app/main.py").write_bytes(b"CHANGED-SYNTHETIC")
        return verified

    monkeypatch.setattr(module, "verify_installation", changed_source)
    output = tmp_path / "payload"
    reject("source_changed", lambda: api().build_payload(source, output, **options))
    assert (output / "app/main.py").read_bytes() == files["app/main.py"]
    assert (output / "aira-installation.json").is_file()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO")
def test_cli_does_not_block_on_a_special_roles_file(tmp_path):
    import json

    source, _, options = staged(tmp_path)
    roles = tmp_path / "roles"
    os.mkfifo(roles)
    output = tmp_path / "payload"
    result = cli(source, output, options, roles)
    assert result.returncode == 2 and result.stdout == b""
    assert json.loads(result.stderr) == {"code": "validation_error"}
    assert not output.exists()


def test_review_destination_created_during_reservation_is_preserved(tmp_path, monkeypatch):
    source, files, options = staged(tmp_path)
    output = tmp_path / "payload"
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == output:
            path.write_bytes(b"SYNTHETIC-OTHER-WRITER")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    reject("destination_exists", lambda: api().build_payload(source, output, **options))
    assert output.read_bytes() == b"SYNTHETIC-OTHER-WRITER"
    assert all((source / name).read_bytes() == data for name, data in files.items())


def test_review_write_failure_closes_every_opened_descriptor(tmp_path, monkeypatch):
    source, _, options = staged(tmp_path)
    original_open, original_close = os.open, os.close
    live = set()

    def opened(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        live.add(fd)
        return fd

    def closed(fd):
        try:
            return original_close(fd)
        finally:
            live.discard(fd)

    def write(*args):
        raise OSError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", opened)
        patch.setattr(os, "close", closed)
        patch.setattr(os, "write", write)
        reject("build_failed", lambda: api().build_payload(source, tmp_path / "payload", **options))
    assert live == set()


def test_review_config_is_captured_before_source_scan(tmp_path, monkeypatch):
    source, _, options = staged(tmp_path)
    expected = dict(options["entrypoints"])
    original = os.scandir

    def scan(*args, **kwargs):
        options["entrypoints"]["frontend"] = "absent"
        return original(*args, **kwargs)

    monkeypatch.setattr(os, "scandir", scan)
    receipt = api().build_payload(source, tmp_path / "payload", **options)
    assert dict(receipt.installation.manifest.entrypoints) == expected


def test_review_cli_output_failure_is_sanitized_without_removing_valid_payload(
    tmp_path, monkeypatch
):
    import builtins
    import json
    import sys

    source, _, options = staged(tmp_path)
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps(options["entrypoints"]))
    destination = tmp_path / "payload"
    module = importlib.import_module("ara.desktop.build.__main__")
    errors = []

    def output(value, **kwargs):
        if kwargs.get("file") is sys.stderr:
            errors.append(value)
        else:
            raise OSError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "print", output)
        status = module.main(
            [
                "--source",
                str(source),
                "--destination",
                str(destination),
                "--version",
                options["version"],
                "--target",
                options["target"],
                "--kind",
                options["kind"],
                "--roles",
                str(roles),
            ]
        )
    assert status == 1 and errors == ['{"code": "build_failed"}']
    assert (destination / "aira-installation.json").is_file()
