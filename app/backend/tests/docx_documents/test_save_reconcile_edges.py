"""Whole-pipeline failure cuts and discard racing an in-flight commit."""

import importlib
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

from ara.documents.storage import DocumentError
from ara.docx_documents import get_docx, save_docx
from ara.docx_documents.save_commit import commit_save
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import api as checkpoints
from tests.acceptance.test_docx_checkpoints import reject
from tests.acceptance.test_docx_save_commit import prepared
from tests.acceptance.test_docx_save_reconcile import api


@pytest.mark.parametrize("step", [1, 2])
@pytest.mark.parametrize("after_commit", [False, True])
def test_reconcile_recovers_each_transaction_ack_boundary(
    run_world, monkeypatch, step, after_commit
):
    runtime, item, pending = prepared(run_world)
    key = uuid4()
    real = runtime.engine.dialect.do_commit
    count = 0

    def fail(connection):
        nonlocal count
        count += 1
        if count == step:
            if after_commit:
                real(connection)
            raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))
        real(connection)

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(
            lambda: api().reconcile_save(runtime, handle=pending.handle, request_id=key),
            "storage_unavailable",
            503,
        )
    observed = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    assert observed.document.storage_revision == (1 if step == 1 and not after_commit else 2)
    assert observed.checkpoint.checkpoint_revision == (3 if step == 2 and after_commit else 2)
    result = api().reconcile_save(runtime, handle=pending.handle, request_id=key)
    assert (
        result.snapshot.document.storage_revision == 2
        and result.snapshot.checkpoint.checkpoint_revision == 3
    )
    assert api().reconcile_save(runtime, handle=pending.handle, request_id=key) == result


@pytest.mark.parametrize("after_commit", [False, True])
def test_discard_ack_loss_does_not_repeat_cleanup(run_world, monkeypatch, after_commit):
    runtime, item, pending = prepared(run_world)
    key = uuid4()
    real = runtime.engine.dialect.do_commit

    def fail(connection):
        if after_commit:
            real(connection)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(
            lambda: api().discard_pending(runtime, handle=pending.handle, request_id=key),
            "storage_unavailable",
            503,
        )
    result = api().discard_pending(runtime, handle=pending.handle, request_id=key)
    assert result.snapshot.checkpoint.checkpoint_revision == 3 and result.snapshot.document == item
    assert api().discard_pending(runtime, handle=pending.handle, request_id=key) == result


def test_discard_and_commit_race_preserves_one_linearized_outcome(run_world):
    runtime, item, pending = prepared(run_world)
    barrier = Barrier(2)

    def save():
        barrier.wait(timeout=5)
        try:
            return commit_save(runtime, handle=pending.handle)
        except DocumentError as error:
            return error

    def discard():
        barrier.wait(timeout=5)
        return api().discard_pending(runtime, handle=pending.handle, request_id=uuid4())

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(save), pool.submit(discard)
        saved, discarded = a.result(timeout=15), b.result(timeout=15)
    current = get_docx(runtime, document_id=item.document_id)
    assert discarded.snapshot.checkpoint.phase == "empty"
    if isinstance(saved, DocumentError):
        assert saved.code == "checkpoint_conflict" and not discarded.save_confirmed
        assert current == item
    else:
        assert discarded.save_confirmed and discarded.receipt == saved.receipt
        assert current == saved.document
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == int(
            discarded.save_confirmed
        )


def test_unconfirmed_foreign_head_discard_does_not_guess_who_saved_it(run_world):
    runtime, item, pending = prepared(run_world)
    newer = save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=item.storage_revision,
        data=item.current_data,
    )
    result = api().discard_pending(runtime, handle=pending.handle, request_id=uuid4())
    assert not result.save_confirmed and result.snapshot.document == newer
    assert get_docx(runtime, document_id=item.document_id) == newer


def test_reply_failure_scope_and_metadata_isolation(run_world, monkeypatch):
    runtime, item, pending = prepared(run_world)
    api()
    model = importlib.import_module("ara.docx_documents.save_models")

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic response failure")

    with monkeypatch.context() as patch:
        patch.setattr(model.DiscardedSave, "__init__", fail)
        reject(
            lambda: api().discard_pending(runtime, handle=pending.handle, request_id=uuid4()),
            "storage_error",
            500,
        )
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == pending.snapshot
    reject(
        lambda: api().discard_pending(
            run_world["runtimes"]["foreign"], handle=pending.handle, request_id=uuid4()
        ),
        "not_found",
        404,
    )
    result = api().discard_pending(runtime, handle=pending.handle, request_id=uuid4())
    original = deepcopy(result.handle)
    object.__setattr__(pending.handle.metadata.origin, "position_id", 999)
    assert result.handle == original


def test_separate_process_reconciles_pending_after_restart(run_world):
    runtime, item, pending = prepared(run_world)
    payload = {
        "url": runtime.engine.url.render_as_string(hide_password=False),
        "user": str(runtime.user_id),
        "project": str(runtime.project_id),
        "document": str(item.document_id),
    }
    script = """
import json,sys
from uuid import UUID,uuid4
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ara.documents.runtime import DocumentRuntime
from ara.docx_documents.checkpoints import get_checkpoint
from ara.docx_documents.save_prepare import _prepared
from ara.docx_documents.save_reconcile import reconcile_save
p=json.load(sys.stdin)
engine=create_engine(p['url'],poolclass=NullPool,hide_parameters=True)
try:
    r=DocumentRuntime(engine=engine,user_id=UUID(p['user']),project_id=UUID(p['project']),mode='local')
    handle=_prepared(get_checkpoint(r,document_id=UUID(p['document']))).handle
    result=reconcile_save(r,handle=handle,request_id=uuid4())
    print(json.dumps({'checkpoint':result.snapshot.checkpoint.checkpoint_revision,
        'phase':result.snapshot.checkpoint.phase,'storage':result.receipt.storage_revision,
        'operation':str(result.handle.operation_id),'current':result.current_matches_receipt}))
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
        "checkpoint": 3,
        "phase": "working",
        "storage": 2,
        "operation": str(pending.handle.operation_id),
        "current": True,
    }
    assert (
        api()
        .reconcile_save(runtime, handle=pending.handle, request_id=uuid4())
        .snapshot.checkpoint.checkpoint_revision
        == 3
    )


def test_reconcile_module_first_import_is_inert():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy
import hashlib,zipfile,xml.etree.ElementTree,typing,datetime,re
from pathlib import Path
import ara.docx_documents,sqlalchemy,psycopg
assert 'ara.docx_documents.save_reconcile' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
    setattr(obj,name,forbidden)
import ara.docx_documents.save_reconcile
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
