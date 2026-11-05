"""Additional lifetime and post-publication preservation review on native macOS."""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_desktop_data_home import api, reject, write_identity
from test_desktop_data_home import root as root

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS lifetime review")


def test_concurrent_close_does_not_release_ownership_early(root, monkeypatch):
    from ara.docx_analysis_worker.macos import RuntimeOwner

    home = api().open_home(root)
    entered, release = threading.Event(), threading.Event()
    original = RuntimeOwner.close

    def held(owner):
        entered.set()
        assert release.wait(5)
        original(owner)

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=1) as pool:
        patch.setattr(RuntimeOwner, "close", held)
        future = pool.submit(home.close)
        try:
            assert entered.wait(3)
            assert home.view().phase == "closing" and home.view().resources_pending
            assert home.close() is False
            reject("home_busy", lambda: api().open_home(root))
        finally:
            release.set()
        assert future.result(timeout=3)
    assert home.view().phase == "closed" and not home.view().resources_pending
    other = api().open_home(root)
    assert other.close()


def test_missing_identity_never_adopts_existing_empty_postgres_directory(root):
    root.mkdir(mode=0o700)
    (root / "postgres").mkdir(mode=0o700)
    reject("home_recovery_required", lambda: api().open_home(root))
    assert not (root / "identity.json").exists() and not list((root / "postgres").iterdir())


def test_validation_failure_releases_native_descriptors_and_can_be_repaired(root):
    write_identity(root, raw=b"invalid")
    before = len(os.listdir("/dev/fd"))
    for _ in range(20):
        reject("home_recovery_required", lambda: api().open_home(root))
    assert len(os.listdir("/dev/fd")) == before
    expected, _ = write_identity(root)
    home = api().open_home(root)
    try:
        assert home.identity().installation_id == expected
    finally:
        assert home.close()
