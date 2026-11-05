"""Commit ACK-loss, concurrency, shared receipt namespace and process recovery."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ara.docx_documents import get_docx
from ara.docx_package.checkpoint import CheckpointMetadata, CheckpointOrigin
from ara.docx_package.editor import EditorSession
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import prepare, reject
from tests.acceptance.test_docx_recovery import request
from tests.acceptance.test_docx_save_commit import api, prepared
from tests.acceptance.test_docx_save_prepare import prepare_save
from tests.acceptance.test_docx_text_edit import client


@pytest.mark.parametrize("after_commit", [False, True])
def test_commit_lost_ack_has_exactly_one_durable_result(run_world, monkeypatch, after_commit):
    runtime, item, pending = prepared(run_world)
    real = runtime.engine.dialect.do_commit

    def fail(connection):
        if after_commit:
            real(connection)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(
            lambda: api().commit_save(runtime, handle=pending.handle), "storage_unavailable", 503
        )
    current = get_docx(runtime, document_id=item.document_id)
    assert current.storage_revision == item.storage_revision + int(after_commit)
    saved = api().commit_save(runtime, handle=pending.handle)
    assert saved.receipt.storage_revision == item.storage_revision + 1
    assert api().commit_save(runtime, handle=pending.handle) == saved
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1


def test_concurrent_commits_share_one_receipt_and_revision(run_world):
    runtime, item, pending = prepared(run_world)
    barrier = Barrier(2)

    def commit():
        barrier.wait(timeout=5)
        return api().commit_save(runtime, handle=pending.handle)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [future.result(timeout=15) for future in (pool.submit(commit), pool.submit(commit))]
    assert a == b and a.current_matches_receipt
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1
        assert conn.scalar(text("SELECT checkpoint_revision FROM docx_editor_checkpoints")) == 2


def test_same_byte_prepared_save_still_has_its_own_revision_and_receipt(run_world):
    runtime, item, _ = prepare(run_world)
    selection = EditorSession(item.current_data).snapshot().selection
    pending = prepare_save(
        runtime,
        item,
        base_storage_revision=item.storage_revision,
        base_sha256=item.current_sha256,
        data=item.current_data,
        metadata=CheckpointMetadata(selection, CheckpointOrigin(uuid4(), 0, 0)),
    )
    result = api().commit_save(runtime, handle=pending.handle)
    assert result.document.current_data == item.current_data
    assert result.receipt.storage_revision == item.storage_revision + 1
    assert result.current_matches_receipt


def test_existing_text_receipt_namespace_cannot_be_reused_for_new_save(run_world):
    runtime, item, pending = prepared(run_world)
    with client(runtime) as http:
        body = request(http, item)["edit"]
        response = http.post(
            f"/docx-documents/{item.document_id}/text-edit",
            json=body,
            headers={"Idempotency-Key": str(pending.handle.operation_id)},
        )
        assert response.status_code == 200
    before = get_docx(runtime, document_id=item.document_id)
    reject(lambda: api().commit_save(runtime, handle=pending.handle), "idempotency_conflict")
    assert get_docx(runtime, document_id=item.document_id) == before


@pytest.mark.parametrize("corruption", ["hash", "size"])
def test_receipt_candidate_corruption_is_not_returned_as_a_success(run_world, corruption):
    runtime, item, pending = prepared(run_world)
    saved = api().commit_save(runtime, handle=pending.handle)
    with runtime.engine.begin() as conn:
        if corruption == "hash":
            conn.execute(text("UPDATE docx_edit_receipts SET current_sha256=:h"), {"h": "0" * 64})
        else:
            conn.execute(
                text("UPDATE docx_edit_receipts SET current_size_bytes=current_size_bytes+1")
            )
        before = conn.execute(text("SELECT * FROM docx_edit_receipts")).all()
    reject(lambda: api().commit_save(runtime, handle=pending.handle), "storage_error", 500)
    assert get_docx(runtime, document_id=item.document_id) == saved.document
    with runtime.engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM docx_edit_receipts")).all() == before


def test_input_handle_is_detached_and_invalid_input_never_opens_database(run_world, monkeypatch):
    runtime, item, pending = prepared(run_world)
    invalid = [None, True, object()]
    damaged = deepcopy(pending.handle)
    object.__delattr__(damaged, "metadata")
    invalid.append(damaged)

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input must not connect")

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine, "connect", forbidden)
        for value in invalid:
            reject(lambda: api().commit_save(runtime, handle=value), "validation_error", 422)
    result = api().commit_save(runtime, handle=pending.handle)
    original = deepcopy(result.handle)
    object.__setattr__(pending.handle.metadata.origin, "position_id", 999)
    assert result.handle == original
    assert get_docx(runtime, document_id=item.document_id).current_sha256 == original.working_sha256


def test_separate_process_commits_the_original_durable_pending(run_world):
    runtime, item, pending = prepared(run_world)
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
from ara.docx_documents.save_commit import commit_save
p=json.load(sys.stdin)
engine=create_engine(p['url'],poolclass=NullPool,hide_parameters=True)
try:
    runtime=DocumentRuntime(engine=engine,user_id=UUID(p['user']),
                           project_id=UUID(p['project']),mode='local')
    handle=_prepared(get_checkpoint(runtime,document_id=UUID(p['document']))).handle
    result=commit_save(runtime,handle=handle)
    print(json.dumps({'operation':str(handle.operation_id),'revision':result.receipt.storage_revision,
                      'sha256':result.receipt.current_sha256,'current':result.current_matches_receipt}))
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
        "operation": str(pending.handle.operation_id),
        "revision": item.storage_revision + 1,
        "sha256": pending.handle.working_sha256,
        "current": True,
    }
    replay = api().commit_save(runtime, handle=pending.handle)
    assert replay.receipt.storage_revision == item.storage_revision + 1


def test_commit_module_import_is_inert():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy
import hashlib,zipfile,xml.etree.ElementTree,typing,datetime,re
from pathlib import Path
import ara.docx_documents,sqlalchemy,psycopg
assert 'ara.docx_documents.save_commit' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
    setattr(obj,name,forbidden)
import ara.docx_documents.save_commit
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
