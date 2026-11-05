"""Independent review: file/command faults, budgets and post-COMMIT cancellation."""

import json
import os
import stat
import sys
import threading
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from test_desktop_postgres_upgrade import (
    V12,
    V13,
    api,
    bundles,
    execute,
    job,
    prepared,
    reject,
    seeded,
    settled,
    stored,
    world,
)

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned upgrade review")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_backup_bytes": True},
        {"max_backup_bytes": 1023},
        {"max_backup_bytes": 8 * 1024**3 + 1},
        {"max_backups": 0},
        {"max_backups": 17},
        {"timeout_seconds": False},
        {"timeout_seconds": 0},
        {"timeout_seconds": 601},
    ],
)
def test_invalid_limits_are_rejected_without_io(kwargs):
    reject("validation_error", lambda: api().UpgradeLimits(**kwargs))


def test_tools_require_closed_absolute_matching_metadata():
    reject("validation_error", lambda: api().UpgradeTools(Path("pg_dump"), Path("pg_restore")))
    reject(
        "validation_error",
        lambda: api().UpgradeTools(
            Path("/SYNTHETIC_PRIVATE/pg_dump"), Path("/elsewhere/pg_restore")
        ),
    )
    assert "SYNTHETIC_PRIVATE" not in repr(
        api().UpgradeTools(
            Path("/SYNTHETIC_PRIVATE/pg_dump"), Path("/SYNTHETIC_PRIVATE/pg_restore")
        )
    )
    assert api().UpgradeError("SYNTHETIC_PRIVATE").code == "upgrade_unavailable"


def test_shutdown_rejects_invalid_budgets_without_io_or_state_change(tmp_path):
    with world(tmp_path) as (home, cluster):
        operation = job(home, cluster)
        for value in (10**1000, float("inf"), float("nan"), -1, 6, True, "SYNTHETIC_PRIVATE"):
            reject("validation_error", lambda: operation.shutdown(value))
            assert operation.view().phase == "new"
            assert list(home.path("backups").iterdir()) == []
        assert operation.shutdown(0)


def test_environment_and_busy_sql_make_no_backups(tmp_path, monkeypatch):
    with world(tmp_path) as (home, cluster):
        before, old = seeded(home, cluster)
        with monkeypatch.context() as patch:
            patch.setenv("PGSERVICE", "SYNTHETIC_PRIVATE")
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "upgrade_unavailable"
        with psycopg.connect(**dict(cluster.connection())) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(1095911745,170302)")
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "upgrade_busy"
            connection.rollback()
        assert not bundles(home)
        assert stored(home, cluster) == before
        assert (home.path("backups") / "schema" / "ready.json").read_bytes() == old


@pytest.mark.parametrize("fault", ["dump", "toc", "disk", "count", "symlink"])
def test_backup_failure_preserves_source_and_prior_files(tmp_path, monkeypatch, fault):
    from ara.desktop.postgres_process import OwnedCommand

    with world(tmp_path) as (home, cluster):
        before, old = seeded(home, cluster)
        root = home.path("backups") / "postgres"
        sentinel = None
        if fault in ("count", "symlink"):
            root.mkdir(mode=0o700)
            folder = root / str(uuid4())
            if fault == "symlink":
                elsewhere = tmp_path / "elsewhere"
                elsewhere.mkdir(mode=0o700)
                folder.symlink_to(elsewhere, target_is_directory=True)
            else:
                folder.mkdir(mode=0o700)
            sentinel = folder / "untouched.bin"
            sentinel.write_bytes(b"SYNTHETIC sentinel")
        original_command, original_sync = OwnedCommand.__init__, os.fsync

        def broken_command(self, owner, executable, args, **kwargs):
            if (fault == "dump" and "--format=custom" in args) or (
                fault == "toc" and "--list" in args
            ):
                args = ("--synthetic-invalid-option",)
            original_command(self, owner, executable, args, **kwargs)

        def broken_sync(fd):
            info = os.fstat(fd)
            if fault == "disk" and stat.S_ISREG(info.st_mode) and info.st_size > 4096:
                if any(p.stat().st_ino == info.st_ino for p in root.glob("*/data.dump.pending")):
                    raise OSError("SYNTHETIC disk failure")
            return original_sync(fd)

        with monkeypatch.context() as patch:
            patch.setattr(OwnedCommand, "__init__", broken_command)
            patch.setattr(os, "fsync", broken_sync)
            operation = job(home, cluster, limits=api().UpgradeLimits(max_backups=1))
            operation.start()
            state = settled(operation)
            assert state.error_code == (
                {"count": "backup_limit_exceeded", "symlink": "upgrade_recovery_required"}.get(
                    fault, "upgrade_unavailable"
                )
            )
        assert stored(home, cluster) == before
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V12,)]
        assert (home.path("backups") / "schema" / "ready.json").read_bytes() == old
        assert not (home.path("backups") / "schema" / "upgrade.json").exists()
        if sentinel is not None:
            assert sentinel.read_bytes() == b"SYNTHETIC sentinel"
        else:
            assert len(bundles(home)) == 1
            assert not (bundles(home)[0] / "backup.json").exists()


@pytest.mark.parametrize("boundary", ["commit", "cleanup_stop", "cleanup_timeout"])
def test_late_stop_or_timeout_does_not_issue_success_or_erase_committed_docx(
    tmp_path, monkeypatch, boundary
):
    from ara.desktop.postgres_upgrade._backend import Backend

    entered, release = threading.Event(), threading.Event()
    with world(tmp_path) as (home, cluster):
        before, _ = seeded(home, cluster)
        original_commit, original_close = psycopg.Connection.commit, Backend.close

        def pause_commit(self):
            result = original_commit(self)
            if (home.path("backups") / "schema" / "upgrade.json").exists():
                entered.set()
                assert release.wait(10)
            return result

        def pause_close(self):
            result = original_close(self)
            if boundary == "cleanup_timeout":
                self.deadline = 0
            entered.set()
            assert release.wait(10)
            return result

        with monkeypatch.context() as patch:
            if boundary == "commit":
                patch.setattr(psycopg.Connection, "commit", pause_commit)
            else:
                patch.setattr(Backend, "close", pause_close)
            operation = job(home, cluster)
            operation.start()
            try:
                assert entered.wait(10)
                reject("invalid_handle", operation.result)
                if boundary != "cleanup_timeout":
                    assert not operation.shutdown(0.01)
            finally:
                release.set()
            result = settled(operation)
            assert result.phase == ("failed" if boundary == "cleanup_timeout" else "closed")
            assert result.error_code == (
                "startup_timeout" if boundary == "cleanup_timeout" else None
            )
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V13,)]
        assert stored(home, cluster) == before
        again = job(home, cluster)
        again.start()
        assert settled(again).phase in ("ready", "not_needed")
        assert len(bundles(home)) == 1
        prepared(home, cluster)
        assert stored(home, cluster) == before


@pytest.mark.parametrize("fault", ["source", "binding", "missing", "partial", "ahead"])
def test_unknown_recovery_state_is_preserved_not_guessed(tmp_path, monkeypatch, fault):
    with world(tmp_path) as (home, cluster):
        before, old = seeded(home, cluster)
        original = command.upgrade

        def failed(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("SYNTHETIC rollback")

        with monkeypatch.context() as patch:
            patch.setattr(command, "upgrade", failed)
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "upgrade_unavailable"
        bundle = bundles(home)[0]
        schema = home.path("backups") / "schema"
        path = bundle / {
            "source": "schema-before.json",
            "binding": "backup.json",
            "missing": "data.dump",
        }.get(fault, "backup.json")
        if fault == "source":
            path.write_bytes(old + b" ")
        elif fault == "binding":
            metadata = json.loads(path.read_bytes())
            metadata["installation_id"] = str(uuid4())
            path.write_text(json.dumps(metadata))
        elif fault == "missing":
            path.unlink()
        elif fault == "partial":
            path = schema / ".ready.json.pending"
            path.write_bytes(b'{"partial":')
            path.chmod(0o600)
        else:
            path = schema / "ready.json"
            record = json.loads(old)
            record["revision"] = V13
            path.write_text(json.dumps(record))
        raw = path.read_bytes() if path.exists() else None
        again = job(home, cluster)
        again.start()
        assert settled(again).error_code == "upgrade_recovery_required"
        assert (path.read_bytes() if path.exists() else None) == raw
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V12,)]
        assert len(bundles(home)) == 1 and stored(home, cluster) == before
