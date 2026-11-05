"""Owned V14 launch, V13 backup upgrade and native file service."""

import json
import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_desktop_composition import api, closed, config, running
from test_desktop_server import wait_for
from test_docx_visible_word import source

from ara.docx_documents.storage import get_docx, import_docx
from ara.docx_files import storage
from ara.docx_files.coordinator import resume
from ara.docx_files.native import NativeFiles, destination

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="owned macOS host")
V13, V14 = "0013_docx_review_preferences", "0014_docx_file_states"


def runtime(desktop):
    return desktop._session.source.document_runtime()


def version(rt):
    with rt.engine.connect() as conn:
        return conn.scalar(text("SELECT version_num FROM alembic_version"))


def create(rt):
    return import_docx(rt, document_id=uuid4(), title="Synthetic native file", data=source("plain"))


def test_fresh_v14_owned_runtime_file_save_and_restart(tmp_path):
    cfg = replace(config(tmp_path), schema_revision=V14)
    target = destination(tmp_path / "saved.docx")
    with running(cfg) as desktop:
        rt = runtime(desktop)
        assert version(rt) == V14
        doc = create(rt)
        storage.prepare(
            rt,
            doc.document_id,
            operation_id=uuid4(),
            expected_version=0,
            storage_revision=doc.storage_revision,
            source_sha256=doc.current_sha256,
            save_as=target,
        )
        done = resume(rt, doc.document_id, files=NativeFiles())
        assert done.state.binding.saved_revision == 1
    with running(cfg) as desktop:
        rt = runtime(desktop)
        assert version(rt) == V14
        assert storage.read(rt, doc.document_id) == done
        assert get_docx(rt, document_id=doc.document_id).current_data == doc.current_data
        assert NativeFiles().selected(target)[1] == doc.current_data


def old_document(tmp_path):
    cfg = config(tmp_path)
    with running(cfg) as desktop:
        rt = runtime(desktop)
        assert version(rt) == V13
        doc = create(rt)
    return cfg, doc


def test_v13_document_retained_through_backup_upgrade(tmp_path):
    cfg, doc = old_document(tmp_path)
    new = replace(cfg, schema_revision=V14)
    with running(new) as desktop:
        rt = runtime(desktop)
        assert version(rt) == V14
        assert get_docx(rt, document_id=doc.document_id).current_data == doc.current_data
        result = desktop._session.upgrade.result()
        assert result.source_revision == V13 and result.target_revision == V14
        assert result.backup_id is not None
        target = destination(tmp_path / "upgraded.docx")
        storage.prepare(
            rt,
            doc.document_id,
            operation_id=uuid4(),
            expected_version=0,
            storage_revision=1,
            source_sha256=doc.current_sha256,
            save_as=target,
        )
        resume(rt, doc.document_id, files=NativeFiles())
    records = list((cfg.home / "backups" / "postgres").glob("*/backup.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_bytes())["source_revision"] == V13
    with running(new) as desktop:
        assert storage.read(runtime(desktop), doc.document_id).state.binding is not None


@pytest.mark.parametrize("point", ["before_commit", "after_commit"])
def test_v14_upgrade_crash_reconciles_exact_document(tmp_path, monkeypatch, point):
    from ara.desktop.postgres_upgrade._backend import Backend
    from ara.desktop.postgres_upgrade._journal import Journal

    cfg, doc = old_document(tmp_path)
    cfg = replace(cfg, schema_revision=V14)
    cls, method = (Backend, "migrate") if point == "before_commit" else (Journal, "finish")
    original = getattr(cls, method)

    def interrupted(self):
        if point == "before_commit":
            original(self)
        raise OSError("synthetic upgrade interruption")

    with monkeypatch.context() as patch:
        patch.setattr(cls, method, interrupted)
        desktop = api().FixtureDesktop(cfg)
        desktop.start()
        wait_for(lambda: desktop.view().phase == "failed", timeout=25)
        closed(desktop)
    with running(cfg) as desktop:
        rt = runtime(desktop)
        assert version(rt) == V14
        assert get_docx(rt, document_id=doc.document_id).current_data == doc.current_data
        assert storage.read(rt, doc.document_id).version == 0
    assert not (cfg.home / "backups" / "schema" / "upgrade.json").exists()


@pytest.mark.parametrize("revision", ["head", "0015_future", None, 14])
def test_unknown_desktop_schema_is_rejected(tmp_path, revision):
    with pytest.raises(api().DesktopError):
        replace(config(tmp_path), schema_revision=revision)
    assert not config(tmp_path).home.exists()


def test_old_profile_does_not_silently_accept_v14(tmp_path):
    cfg = replace(config(tmp_path), schema_revision=V14)
    with running(cfg):
        pass
    desktop = api().FixtureDesktop(replace(cfg, schema_revision=V13))
    desktop.start()
    wait_for(lambda: desktop.view().phase == "failed", timeout=25)
    closed(desktop)
    with running(cfg) as desktop:
        assert version(runtime(desktop)) == V14
