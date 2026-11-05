"""Immutable prepare proof at ACK-loss, revision limits and supersession."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ara.docx_documents import get_docx, save_docx
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import api as checkpoints
from tests.acceptance.test_docx_checkpoints import prepare, reject, working
from tests.acceptance.test_docx_save_prepare import api, prepare_save

MAX = 9223372036854775807


@pytest.mark.parametrize("after_commit", [False, True])
def test_prepare_lost_ack_repeats_same_pending_and_operation(run_world, monkeypatch, after_commit):
    runtime, item, _ = prepare(run_world)
    values, key, operation = working(item), uuid4(), uuid4()
    real = runtime.engine.dialect.do_commit

    def fail(connection):
        if after_commit:
            real(connection)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(
            lambda: prepare_save(runtime, item, request_id=key, operation_id=operation, **values),
            "storage_unavailable",
            503,
        )
    saved = prepare_save(runtime, item, request_id=key, operation_id=operation, **values)
    assert saved.handle.operation_id == operation and saved.handle.prepared_checkpoint_revision == 2
    assert prepare_save(runtime, item, request_id=key, operation_id=operation, **values) == saved
    assert saved.snapshot.document == item


@pytest.mark.parametrize("limit", ["checkpoint", "storage"])
def test_prepare_cannot_create_an_unfinishable_overflow_state(run_world, limit):
    runtime, item, _ = prepare(run_world)
    with runtime.engine.begin() as conn:
        if limit == "checkpoint":
            conn.execute(
                text("UPDATE docx_editor_checkpoints SET checkpoint_revision=:r"), {"r": MAX}
            )
        else:
            conn.execute(
                text("UPDATE docx_documents SET storage_revision=:r WHERE id=:id"),
                {"r": MAX, "id": item.document_id},
            )
    current = get_docx(runtime, document_id=item.document_id)
    reject(
        lambda: prepare_save(
            runtime, current, expected=MAX if limit == "checkpoint" else 1, **working(current)
        ),
        "revision_exhausted",
    )
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.phase
        == "empty"
    )


def test_replay_returns_original_proof_and_current_head_separately(run_world):
    runtime, item, _ = prepare(run_world)
    values, key, operation = working(item), uuid4(), uuid4()
    original = prepare_save(runtime, item, request_id=key, operation_id=operation, **values)
    save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=item.storage_revision,
        data=item.current_data,
    )
    replay = prepare_save(runtime, item, request_id=key, operation_id=operation, **values)
    assert (
        replay.handle == original.handle
        and replay.snapshot.checkpoint == original.snapshot.checkpoint
    )
    assert replay.snapshot.document.storage_revision == item.storage_revision + 1


def test_old_proof_validates_after_checkpoint_removal_and_rejects_all_modified_fields(run_world):
    runtime, item, _ = prepare(run_world)
    saved = prepare_save(runtime, item, **working(item))
    with runtime.engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE docx_editor_checkpoints SET phase='empty',checkpoint_revision=3,
            base_storage_revision=NULL,base_sha256=NULL,working_data=NULL,
            working_sha256=NULL,metadata=NULL,last_request_id=NULL,last_request_sha256=NULL
        """)
        )
    saved.handle.__post_init__()
    for name in ("prepared_checkpoint_revision", "base_storage_revision", "working_size_bytes"):
        damaged = deepcopy(saved.handle)
        object.__setattr__(damaged, name, getattr(damaged, name) + 1)
        with pytest.raises(ValueError):
            damaged.__post_init__()
    for name in ("document_id", "metadata", "working_sha256"):
        damaged = deepcopy(saved.handle)
        object.__delattr__(damaged, name)
        with pytest.raises(ValueError):
            damaged.__post_init__()


def test_invalid_requests_never_persist_pending(run_world):
    runtime, item, empty = prepare(run_world)
    values = working(item)
    for changes in (
        {"operation_id": True},
        {"request_id": "bad"},
        {"expected_checkpoint_revision": False},
        {"base_sha256": "A" * 64},
    ):
        kwargs = dict(
            document_id=item.document_id,
            expected_checkpoint_revision=1,
            request_id=uuid4(),
            operation_id=uuid4(),
            **values,
        )
        kwargs.update(changes)
        reject(lambda: api().prepare_save(runtime, **kwargs), "validation_error", 422)
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == empty


def test_prepare_modules_first_import_has_no_external_side_effects():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy
import hashlib,zipfile,xml.etree.ElementTree,typing,datetime,re
from pathlib import Path
import ara.docx_documents,sqlalchemy,psycopg
assert 'ara.docx_documents.save_prepare' not in sys.modules
assert 'ara.docx_documents.save_models' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
    setattr(obj,name,forbidden)
import ara.docx_documents.save_prepare
import ara.docx_documents.save_models
"""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout


def test_prepared_identity_is_reconstructed_by_a_separate_process(run_world):
    runtime, item, _ = prepare(run_world)
    prepared = prepare_save(runtime, item, **working(item))
    payload = {
        "url": runtime.engine.url.render_as_string(hide_password=False),
        "user": str(runtime.user_id),
        "project": str(runtime.project_id),
        "document": str(item.document_id),
    }
    script = """
import json,sys
from uuid import UUID
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ara.documents.runtime import DocumentRuntime
from ara.docx_documents.checkpoints import get_checkpoint
from ara.docx_documents.save_prepare import _prepared
p=json.load(sys.stdin)
engine=create_engine(p['url'],poolclass=NullPool,hide_parameters=True)
try:
    runtime=DocumentRuntime(engine=engine,user_id=UUID(p['user']),
                           project_id=UUID(p['project']),mode='local')
    prepared=_prepared(get_checkpoint(runtime,document_id=UUID(p['document'])))
    h=prepared.handle
    h.__post_init__()
    print(json.dumps({'operation':str(h.operation_id),'fingerprint':h.request_sha256,
                      'checkpoint':h.prepared_checkpoint_revision,'candidate':h.working_sha256,
                      'current_revision':prepared.snapshot.document.storage_revision}))
finally:engine.dispose()
"""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "operation": str(prepared.handle.operation_id),
        "fingerprint": prepared.handle.request_sha256,
        "checkpoint": 2,
        "candidate": prepared.handle.working_sha256,
        "current_revision": item.storage_revision,
    }
