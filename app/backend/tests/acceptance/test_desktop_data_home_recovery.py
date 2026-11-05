"""First-launch cutpoints and preservation of the published installation identity."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from test_desktop_data_home import NAMES, api, reject, write_identity
from test_desktop_data_home import root as root

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS data-home recovery")


def crash_after_sync(root, *, published):
    program = """
import os,stat,sys
from pathlib import Path
from ara.desktop.data_home import open_home
root=Path(sys.argv[1])
published=sys.argv[2]=='1'
original=os.fsync
def cut(fd):
    original(fd)
    info=os.fstat(fd)
    if published and stat.S_ISDIR(info.st_mode) and (root/'identity.json').exists():
        os._exit(73)
    if not published and stat.S_ISREG(info.st_mode) and info.st_size>0:
        os._exit(73)
os.fsync=cut
open_home(root)
raise AssertionError('Cutpoint was not reached')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(root), "1" if published else "0"],
        env={
            "PYTHONPATH": str(Path.cwd() / "src"),
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "PYTHONUTF8": "1",
        },
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 73 and not result.stdout and not result.stderr


@pytest.mark.parametrize("published", [False, True])
def test_actual_process_exit_preserves_staged_or_published_uuid(root, published):
    crash_after_sync(root, published=published)
    path = root / ("identity.json" if published else ".identity.pending")
    original = path.read_bytes()
    identity = UUID(json.loads(original)["installation_id"])
    assert not (root / "postgres").exists()
    home = api().open_home(root)
    try:
        assert home.identity().installation_id == identity
        assert (root / "identity.json").read_bytes() == original
        assert {p.name for p in root.iterdir()} == NAMES
    finally:
        assert home.close()


def test_partial_unpublished_stage_recovered_only_when_pristine(root):
    write_identity(root, stage=True, raw=b'{"schema_version":')
    home = api().open_home(root)
    try:
        assert home.identity().installation_id.version == 4
        assert not (root / ".identity.pending").exists()
        assert {p.name for p in root.iterdir()} == NAMES
    finally:
        assert home.close()


def test_valid_staging_uuid_is_reused(root):
    expected, raw = write_identity(root, stage=True)
    home = api().open_home(root)
    try:
        assert home.identity().installation_id == expected
        assert (root / "identity.json").read_bytes() == raw
    finally:
        assert home.close()


def test_final_and_staging_conflict_preserved_for_recovery(root):
    _, final = write_identity(root)
    _, stage = write_identity(root, stage=True)
    reject("home_recovery_required", lambda: api().open_home(root))
    assert (root / "identity.json").read_bytes() == final
    assert (root / ".identity.pending").read_bytes() == stage
    assert not (root / "postgres").exists()


def test_write_failure_does_not_return_home_or_start_other_components(root, monkeypatch):
    original = os.write
    fired = False

    def partial(fd, data):
        nonlocal fired
        if data and not fired:
            fired = True
            original(fd, data[:5])
            raise OSError("SYNTHETIC_PRIVATE")
        return original(fd, data)

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", partial)
        reject("home_unavailable", lambda: api().open_home(root))
    assert fired and not (root / "identity.json").exists() and not (root / "postgres").exists()
    home = api().open_home(root)
    assert home.close()


def test_post_publication_flush_failure_does_not_erase_final(root, monkeypatch):
    original = os.fsync
    fired = False

    def broken(fd):
        nonlocal fired
        if stat.S_ISDIR(os.fstat(fd).st_mode) and (root / "identity.json").exists():
            fired = True
            raise OSError("SYNTHETIC_PRIVATE")
        return original(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", broken)
        reject("home_unavailable", lambda: api().open_home(root))
    assert fired and not (root / "postgres").exists()
    data = (root / "identity.json").read_bytes()
    expected = UUID(json.loads(data)["installation_id"])
    home = api().open_home(root)
    try:
        assert home.identity().installation_id == expected
        assert (root / "identity.json").read_bytes() == data
    finally:
        assert home.close()


def test_existing_identity_is_never_rewritten(root, monkeypatch):
    value, raw = write_identity(root, uuid4())

    def forbidden(*args, **kwargs):
        raise AssertionError("Existing identity was rewritten")

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", forbidden)
        home = api().open_home(root)
        try:
            assert home.identity().installation_id == value
            assert (root / "identity.json").read_bytes() == raw
        finally:
            assert home.close()
