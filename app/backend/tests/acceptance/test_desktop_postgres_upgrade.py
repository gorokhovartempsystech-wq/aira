"""Bounded owned upgrade with an actual restorable backup, never the main database."""

import importlib
import json
import sys
import time
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import make_conninfo
from test_desktop_postgres_schema import V8, V13, engine_for, execute, prepared, relations, world

V12 = "0012_docx_continuous_timeout"
DOC = UUID("77777777-7777-4777-8777-777777777777")
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned PostgreSQL upgrade")


def api():
    return importlib.import_module("ara.desktop.postgres_upgrade")


def tools():
    bin = Path.cwd() / ".runtime/Postgres.app/Contents/Versions/18/bin"
    return api().UpgradeTools(bin / "pg_dump", bin / "pg_restore")


def job(home, cluster, **kwargs):
    return api().UpgradePreparation(
        home, cluster, migrations=Path.cwd() / "migrations", tools=tools(), **kwargs
    )


def settled(operation):
    end = time.monotonic() + 30
    while time.monotonic() < end:
        state = operation.view()
        if (
            state.phase in ("ready", "not_needed", "failed", "closed")
            and not state.resources_pending
        ):
            return state
        time.sleep(0.01)
    pytest.fail("Synthetic upgrade did not settle")


def upgraded(home, cluster):
    operation = job(home, cluster)
    operation.start()
    assert settled(operation).phase == "ready", operation.view()
    return operation


def reject(code, call):
    with pytest.raises(api().UpgradeError) as caught:
        call()
    assert caught.value.code == code
    assert "SYNTHETIC_PRIVATE" not in str(caught.value) + repr(caught.value)


def payload():
    from ara.docx_package.creation import NewParagraph, create_docx

    return create_docx((NewParagraph("Synthetic upgrade must preserve this DOCX."),))


def stored(home, cluster):
    from ara.documents.runtime import DocumentRuntime
    from ara.docx_documents import get_docx

    with engine_for(cluster) as engine:
        identity = home.identity()
        runtime = DocumentRuntime(
            engine=engine, user_id=identity.user_id, project_id=identity.project_id, mode="local"
        )
        return get_docx(runtime, document_id=DOC)


def seeded(home, cluster):
    from ara.documents.runtime import DocumentRuntime
    from ara.docx_documents import import_docx

    identity, physical = home.identity(), cluster.identity()
    with engine_for(cluster) as engine:
        with engine.begin() as connection:
            cfg = Config()
            cfg.set_main_option("script_location", str(Path.cwd() / "migrations"))
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, V12)
            connection.exec_driver_sql("INSERT INTO users(id) VALUES (%s)", (identity.user_id,))
            connection.exec_driver_sql(
                "INSERT INTO projects(id,owner_id,name) VALUES (%s,%s,'AIRA')",
                (identity.project_id, identity.user_id),
            )
            connection.exec_driver_sql(
                "UPDATE docx_analysis_supervisor SET phase='clean',revision=2,installation_id=%s",
                (identity.installation_id,),
            )
        runtime = DocumentRuntime(
            engine=engine, user_id=identity.user_id, project_id=identity.project_id, mode="local"
        )
        before = import_docx(runtime, document_id=DOC, title="Synthetic upgrade", data=payload())
    record = dict(
        schema_version="aira-schema-ready/1",
        installation_id=str(identity.installation_id),
        user_id=str(identity.user_id),
        project_id=str(identity.project_id),
        system_identifier=physical.system_identifier,
        database_oid=physical.database_oid,
        revision=V12,
    )
    directory = home.path("backups") / "schema"
    directory.mkdir(mode=0o700)
    raw = (json.dumps(record, indent=2) + "\n").encode()
    (directory / "ready.json").write_bytes(raw)
    (directory / "ready.json").chmod(0o600)
    return before, raw


def bundles(home):
    root = home.path("backups") / "postgres"
    return [p for p in root.iterdir() if p.is_dir()] if root.exists() else []


@pytest.mark.parametrize("late_write", [False, True])
def test_upgrade_preserves_docx_and_produces_real_restorable_backup(
    tmp_path, monkeypatch, late_write
):
    from ara.desktop.postgres_process import OwnedCommand
    from ara.documents.runtime import DocumentRuntime
    from ara.docx_analysis_worker.macos import acquire_owner
    from ara.docx_documents import get_docx

    second = tmp_path / "second"
    second.mkdir()
    with world(tmp_path) as (home, cluster), world(second) as (target_home, target):
        before, old_ready = seeded(home, cluster)
        physical = cluster.identity()
        seen = []
        original_command = OwnedCommand.__init__

        def command_with_late_write(self, owner, executable, args, **kwargs):
            original_command(self, owner, executable, args, **kwargs)
            if executable.name == "pg_dump" and "--format=custom" in args:
                assert any(arg.startswith("--snapshot=") for arg in args)
                seen.append(True)
                if late_write:
                    execute(
                        cluster,
                        "UPDATE docx_documents SET title='Late synthetic write' WHERE id=%s",
                        (DOC,),
                    )

        monkeypatch.setattr(OwnedCommand, "__init__", command_with_late_write)
        operation = upgraded(home, cluster)
        assert seen == [True]
        after = stored(home, cluster)
        assert after.current_data == before.current_data
        assert after.title == ("Late synthetic write" if late_write else before.title)
        result = operation.result()
        assert (result.source_revision, result.target_revision) == (V12, V13)
        assert (result.installation_id, result.system_identifier, result.database_oid) == (
            physical.installation_id,
            physical.system_identifier,
            physical.database_oid,
        )
        archive = operation.backup_path()
        assert archive == home.path("backups") / "postgres" / str(result.backup_id) / "data.dump"
        assert sha256(archive.read_bytes()).hexdigest() == result.backup_sha256
        assert archive.stat().st_size == result.backup_size_bytes > 0
        assert (archive.parent / "schema-before.json").read_bytes() == old_ready
        metadata = json.loads((archive.parent / "backup.json").read_bytes())
        assert metadata["archive_sha256"] == result.backup_sha256
        assert metadata["source_ready_sha256"] == sha256(old_ready).hexdigest()
        assert metadata["source_revision"] == V12
        assert stored(home, cluster) == after
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V13,)]
        assert not (home.path("backups") / "schema" / "upgrade.json").exists()
        assert not (home.path("backups") / "schema" / ".ready.json.pending").exists()
        prepared(home, cluster)
        assert stored(home, cluster) == after
        again = job(home, cluster)
        again.start()
        assert settled(again).phase == "not_needed"
        assert again.result().backup_id is None
        assert len(bundles(home)) == 1

        root = tmp_path / "restore-owner"
        root.mkdir(mode=0o700)
        owner = acquire_owner(root)
        command_job = OwnedCommand(
            owner,
            tools().restore,
            (
                "--single-transaction",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--no-password",
                "--dbname=" + make_conninfo(**dict(target.connection())),
                str(archive),
            ),
            cwd=root,
        )
        try:
            command_job.start()
            end = time.monotonic() + 20
            while command_job.view().resources_pending and time.monotonic() < end:
                time.sleep(0.01)
            assert command_job.view().phase == "exited" and command_job.view().returncode == 0
            with engine_for(target) as engine:
                scope = home.identity()
                runtime = DocumentRuntime(
                    engine=engine, user_id=scope.user_id, project_id=scope.project_id, mode="local"
                )
                assert get_docx(runtime, document_id=DOC) == before
            assert execute(target, "SELECT version_num FROM alembic_version") == [(V12,)]
        finally:
            assert command_job.shutdown(5)
            owner.close()


def test_empty_noop_and_new_shutdown_are_inert(tmp_path):
    with world(tmp_path) as (home, cluster):
        operation = job(home, cluster)
        assert operation.view().phase == "new" and not operation.view().resources_pending
        assert list(home.path("backups").iterdir()) == []
        reject("invalid_handle", operation.result)
        operation.start()
        assert settled(operation).phase == "not_needed"
        result = operation.result()
        assert result.source_revision is result.target_revision is result.backup_id is None
        assert list(home.path("backups").iterdir()) == []
        assert relations(cluster) == []
        reject("invalid_handle", operation.backup_path)
        untouched = job(home, cluster)
        assert untouched.shutdown(0)
        reject("invalid_handle", untouched.start)


@pytest.mark.parametrize("case", ["missing", "foreign", "corrupt", "active"])
def test_unproven_or_active_predecessor_is_not_modified(tmp_path, case):
    with world(tmp_path) as (home, cluster):
        before, _ = seeded(home, cluster)
        marker = home.path("backups") / "schema" / "ready.json"
        if case == "missing":
            marker.unlink()
        elif case == "foreign":
            record = json.loads(marker.read_bytes())
            record["installation_id"] = str(uuid4())
            marker.write_text(json.dumps(record))
        elif case == "corrupt":
            marker.write_bytes(b'{"corrupt":')
        else:
            values = tuple(uuid4() for _ in range(6))
            execute(
                cluster,
                "UPDATE docx_analysis_supervisor SET phase='armed',revision=5,"
                "owner_epoch=%s,launch_id=%s,document_id=%s,run_id=%s,attempt_id=%s,"
                "worker_instance_id=%s,claim_fence=1",
                values,
            )
        original = marker.read_bytes() if marker.exists() else None
        operation = job(home, cluster)
        operation.start()
        assert settled(operation).error_code == (
            "upgrade_busy" if case == "active" else "upgrade_recovery_required"
        )
        assert stored(home, cluster) == before
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V12,)]
        assert (marker.read_bytes() if marker.exists() else None) == original
        assert not bundles(home)


def test_v8_never_upgraded_or_adopted(tmp_path):
    with world(tmp_path) as (home, cluster):
        with engine_for(cluster) as engine, engine.begin() as connection:
            cfg = Config()
            cfg.set_main_option("script_location", str(Path.cwd() / "migrations"))
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, V8)
        before = relations(cluster)
        operation = job(home, cluster)
        operation.start()
        assert settled(operation).error_code == "unsupported_revision"
        assert relations(cluster) == before
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V8,)]


def test_backup_limit_preserves_source_and_partial_copy(tmp_path):
    with world(tmp_path) as (home, cluster):
        before, old_ready = seeded(home, cluster)
        operation = job(home, cluster, limits=api().UpgradeLimits(max_backup_bytes=1024))
        operation.start()
        assert settled(operation).error_code == "backup_limit_exceeded"
        assert stored(home, cluster) == before
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V12,)]
        assert (home.path("backups") / "schema" / "ready.json").read_bytes() == old_ready
        assert len(bundles(home)) == 1
        assert not (home.path("backups") / "schema" / "upgrade.json").exists()


@pytest.mark.parametrize("corrupt", [False, True])
def test_failed_transaction_keeps_backup_and_reconciles_without_duplicate_copy(
    tmp_path, monkeypatch, corrupt
):
    original = command.upgrade

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC_PRIVATE after DDL")

    with world(tmp_path) as (home, cluster):
        before, old_ready = seeded(home, cluster)
        with monkeypatch.context() as patch:
            patch.setattr(command, "upgrade", fail)
            operation = job(home, cluster)
            operation.start()
            assert settled(operation).error_code == "upgrade_unavailable"
        assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V12,)]
        assert stored(home, cluster) == before
        assert (home.path("backups") / "schema" / "ready.json").read_bytes() == old_ready
        assert (home.path("backups") / "schema" / "upgrade.json").exists()
        copies = bundles(home)
        assert len(copies) == 1
        backup = (copies[0] / "data.dump").read_bytes()
        if corrupt:
            (copies[0] / "data.dump").write_bytes(backup + b"SYNTHETIC_DAMAGE")
            again = job(home, cluster)
            again.start()
            assert settled(again).error_code == "upgrade_recovery_required"
            assert execute(cluster, "SELECT version_num FROM alembic_version") == [(V12,)]
        else:
            again = upgraded(home, cluster)
            assert again.backup_path() == copies[0] / "data.dump"
            assert again.backup_path().read_bytes() == backup
            assert len(bundles(home)) == 1
            prepared(home, cluster)
        assert stored(home, cluster) == before
