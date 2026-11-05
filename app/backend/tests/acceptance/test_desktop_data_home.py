"""Independent data-home acceptance on disposable directories, never the real profile."""

import copy
import importlib
import json
import os
import pickle
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS data-home gate")
NAMES = {"runtime.owner", "identity.json", "postgres", "analysis", "license", "backups"}


def api():
    return importlib.import_module("ara.desktop.data_home")


def reject(code, call):
    with pytest.raises(api().HomeError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


@pytest.fixture
def root(tmp_path):
    return tmp_path.resolve() / "SYNTHETIC_PRIVATE"


def write_identity(root, value=None, *, stage=False, raw=None):
    root.mkdir(mode=0o700, exist_ok=True)
    value = uuid4() if value is None else value
    raw = (
        json.dumps(dict(schema_version="aira-data-home/1", installation_id=str(value))).encode()
        if raw is None
        else raw
    )
    path = root / (".identity.pending" if stage else "identity.json")
    path.write_bytes(raw)
    path.chmod(0o600)
    return value, raw


def child(root, body):
    program = (
        "from pathlib import Path\n"
        "from ara.desktop.data_home import open_home,HomeError\n"
        "import sys\n"
        "root=Path(sys.argv[1])\n"
    ) + body
    result = subprocess.run(
        [sys.executable, "-c", program, str(root)],
        env={
            "PYTHONPATH": str(Path.cwd() / "src"),
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "PYTHONUTF8": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, "Synthetic data-home child failed"
    assert result.stdout.strip() == "ok" and not result.stderr


def test_first_open_is_private_and_reopen_preserves_identity(root):
    home = api().open_home(root)
    try:
        identity = home.identity()
        assert type(identity.installation_id) is UUID and identity.installation_id.version == 4
        assert identity.user_id == uuid5(identity.installation_id, "aira/local-user/1")
        assert identity.project_id == uuid5(identity.installation_id, "aira/local-project/1")
        assert identity.user_id != identity.project_id
        assert {p.name for p in root.iterdir()} == NAMES
        assert json.loads((root / "identity.json").read_bytes()) == dict(
            schema_version="aira-data-home/1", installation_id=str(identity.installation_id)
        )
        for name in ("root", "postgres", "analysis", "license", "backups"):
            path = home.path(name)
            assert path == (root if name == "root" else root / name)
            assert stat.S_IMODE(path.stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "identity.json").stat().st_mode) == 0o600
        assert home.view().phase == "open" and home.view().resources_pending
        assert "SYNTHETIC_PRIVATE" not in repr(home) + repr(home.view())
        reject("validation_error", lambda: home.path("../outside"))
        before = (root / "identity.json").read_bytes()
    finally:
        assert home.close()
    assert home.view().phase == "closed" and not home.view().resources_pending
    assert home.close()
    reject("invalid_handle", home.identity)
    reopened = api().open_home(root)
    try:
        assert reopened.identity() == identity
        assert (root / "identity.json").read_bytes() == before
    finally:
        assert reopened.close()


def test_existing_document_directories_not_scanned_or_modified(root):
    value, _ = write_identity(root)
    (root / "postgres").mkdir(mode=0o700)
    (root / "postgres" / "user-document").write_bytes(b"preserve")
    home = api().open_home(root)
    try:
        assert home.identity().installation_id == value
        assert (root / "postgres" / "user-document").read_bytes() == b"preserve"
    finally:
        assert home.close()


def test_single_instance_across_processes_and_separate_analysis_owner(root):
    from ara.docx_analysis_worker.macos import acquire_owner

    home = api().open_home(root)
    try:
        reject("home_busy", lambda: api().open_home(root))
        child(
            root,
            (
                "try:\n"
                " open_home(root)\n"
                "except HomeError as e:\n"
                " assert e.code=='home_busy'\n"
                " print('ok')\n"
                "else:\n"
                " raise AssertionError()\n"
            ),
        )
        analysis = acquire_owner(home.path("analysis"))
        analysis.close()
    finally:
        assert home.close()
    child(root, "h=open_home(root)\nassert h.close()\nprint('ok')\n")


def test_handles_cannot_be_copied_or_used_after_fork(root, monkeypatch):
    home = api().open_home(root)
    try:
        for operation in (
            lambda: copy.copy(home),
            lambda: copy.deepcopy(home),
            lambda: pickle.dumps(home),
        ):
            reject("invalid_handle", operation)
        with monkeypatch.context() as patch:
            patch.setattr(os, "getpid", lambda: -1)
            for operation in (home.identity, home.view, home.close, lambda: home.path("root")):
                reject("invalid_handle", operation)
    finally:
        assert home.close()


def test_lost_caller_reference_does_not_drop_owner(root):
    child(
        root,
        (
            "import gc\n"
            "h=open_home(root)\n"
            "del h\n"
            "gc.collect()\n"
            "try:\n"
            " open_home(root)\n"
            "except HomeError as e:\n"
            " assert e.code=='home_busy'\n"
            " print('ok')\n"
            "else:\n"
            " raise AssertionError()\n"
        ),
    )
    home = api().open_home(root)
    assert home.close()


def test_close_error_retains_quarantine_in_own_process(root):
    child(
        root,
        (
            "from ara.docx_analysis_worker.macos import RuntimeOwner\n"
            "h=open_home(root)\n"
            "original=RuntimeOwner.close\n"
            "def broken(self):\n"
            " original(self)\n"
            " raise OSError('SYNTHETIC_PRIVATE')\n"
            "RuntimeOwner.close=broken\n"
            "assert h.close() is False\n"
            "assert h.view().phase=='failed' and h.view().resources_pending\n"
            "RuntimeOwner.close=original\n"
            "assert h.close() is False\n"
            "try:\n"
            " open_home(root)\n"
            "except HomeError as e:\n"
            " assert e.code=='home_busy'\n"
            " print('ok')\n"
            "else:\n"
            " raise AssertionError()\n"
        ),
    )


def test_default_root_is_explicit_readonly_native_lookup(tmp_path, monkeypatch):
    import pwd

    module = api()
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(tmp_path)))
    assert module.default_root() == tmp_path / "Library" / "Application Support" / "AIRA"
    assert not list(tmp_path.iterdir())
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "unsupported")
        reject("unsupported_platform", module.default_root)


@pytest.mark.parametrize(
    "value",
    [Path("relative"), Path("/a/../b"), Path("/"), Path("/bad\x00name"), "SYNTHETIC_PRIVATE"],
)
def test_invalid_root_rejected_without_creation(value):
    reject("validation_error", lambda: api().open_home(value))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{}",
        b"[]",
        b"null",
        b"\xff",
        b"x" * 1025,
        b'{"schema_version":"aira-data-home/1","installation_id":"bad"}',
        b'{"schema_version":"aira-data-home/1","installation_id":true}',
        b'{"schema_version":"aira-data-home/1","installation_id":"00000000-0000-0000-0000-000000000000"}',
    ],
)
def test_corrupt_final_identity_is_never_reset(root, raw):
    write_identity(root, raw=raw)
    reject("home_recovery_required", lambda: api().open_home(root))
    assert (root / "identity.json").read_bytes() == raw
    assert not (root / "postgres").exists()


def test_duplicate_unknown_and_noncanonical_identity_rejected(root):
    value, raw = write_identity(root, UUID("a1234567-1234-4234-8234-123456789abc"))
    for data in (
        raw[:-1] + b',"installation_id":"' + str(value).encode() + b'"}',
        raw[:-1] + b',"extra":true}',
        raw.replace(str(value).encode(), str(value).upper().encode()),
    ):
        (root / "identity.json").write_bytes(data)
        reject("home_recovery_required", lambda: api().open_home(root))
        assert (root / "identity.json").read_bytes() == data


@pytest.mark.parametrize("kind", ["child_dir", "user_file", "partial_with_user_file"])
def test_missing_identity_with_user_data_never_regenerates_or_deletes(root, kind):
    root.mkdir(mode=0o700)
    if kind == "child_dir":
        (root / "postgres").mkdir(mode=0o700)
        sentinel = root / "postgres" / "sentinel"
    else:
        sentinel = root / "notes.txt"
    sentinel.write_bytes(b"user-sentinel")
    if kind == "partial_with_user_file":
        write_identity(root, stage=True, raw=b'{"schema_version":')
    reject("home_recovery_required", lambda: api().open_home(root))
    assert sentinel.read_bytes() == b"user-sentinel" and not (root / "identity.json").exists()
    if kind == "partial_with_user_file":
        assert (root / ".identity.pending").read_bytes() == b'{"schema_version":'


@pytest.mark.parametrize(
    "kind",
    [
        "root_link",
        "parent_link",
        "file_link",
        "hardlink",
        "fifo",
        "directory",
        "root_mode",
        "file_mode",
    ],
)
def test_unsafe_paths_not_adopted_or_repaired(root, kind):
    write_identity(root)
    original = (root / "identity.json").read_bytes()
    candidate = root
    outside = root.parent / "outside"
    if kind == "root_link":
        candidate = root.parent / "alias"
        candidate.symlink_to(root, target_is_directory=True)
    elif kind == "parent_link":
        alias = root.parent / "alias"
        alias.symlink_to(root.parent, target_is_directory=True)
        candidate = alias / root.name
    elif kind == "root_mode":
        root.chmod(0o755)
    elif kind == "file_mode":
        (root / "identity.json").chmod(0o644)
    else:
        path = root / "identity.json"
        path.unlink()
        outside.write_bytes(original)
        if kind == "file_link":
            path.symlink_to(outside)
        elif kind == "hardlink":
            os.link(outside, path)
        elif kind == "fifo":
            os.mkfifo(path, 0o600)
        else:
            path.mkdir(mode=0o700)
    # Metadata failures cannot be mistaken for an absent first installation.
    with pytest.raises(api().HomeError) as caught:
        api().open_home(candidate)
    assert caught.value.code in {"home_unavailable", "home_recovery_required"}
    assert not (root / "postgres").exists()
    if outside.exists():
        assert outside.read_bytes() == original
    if kind == "root_mode":
        assert stat.S_IMODE(root.stat().st_mode) == 0o755
    if kind == "file_mode":
        assert stat.S_IMODE((root / "identity.json").stat().st_mode) == 0o644
