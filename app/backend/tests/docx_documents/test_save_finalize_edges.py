"""Finalize ACK-loss, concurrent recovery and control-proof integrity."""

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

from ara.docx_documents.save_commit import commit_save
from ara.docx_documents.save_finalize import _control_fingerprint
from ara.docx_package.checkpoint import encode_metadata
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import api as checkpoints
from tests.acceptance.test_docx_checkpoints import reject, working
from tests.acceptance.test_docx_save_commit import prepared
from tests.acceptance.test_docx_save_finalize import api


@pytest.mark.parametrize("after_commit", [False, True])
def test_finalize_ack_loss_does_not_resave_or_repeat_cleanup(run_world, monkeypatch, after_commit):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    key = uuid4()
    real = runtime.engine.dialect.do_commit

    def fail(connection):
        if after_commit:
            real(connection)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(
            lambda: api().finalize_save(runtime, handle=pending.handle, request_id=key),
            "storage_unavailable",
            503,
        )
    observed = checkpoints().get_checkpoint(runtime, document_id=item.document_id)
    assert observed.checkpoint.checkpoint_revision == (3 if after_commit else 2)
    result = api().finalize_save(runtime, handle=pending.handle, request_id=key)
    assert result.snapshot.checkpoint.checkpoint_revision == 3
    assert api().finalize_save(runtime, handle=pending.handle, request_id=key) == result
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 1
        assert (
            conn.scalar(
                text("SELECT storage_revision FROM docx_documents WHERE id=:id"),
                {"id": item.document_id},
            )
            == 2
        )


def test_two_recovering_windows_finalize_one_checkpoint(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    barrier = Barrier(2)

    def finalize():
        barrier.wait(timeout=5)
        return api().finalize_save(runtime, handle=pending.handle, request_id=uuid4())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(finalize), pool.submit(finalize))
        a, b = [f.result(timeout=15) for f in futures]
    assert a == b and a.snapshot.checkpoint.checkpoint_revision == 3


def test_status_of_discarded_uncommitted_work_is_superseded_and_read_only(run_world):
    runtime, item, pending = prepared(run_world)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE docx_editor_checkpoints SET phase='empty',checkpoint_revision=3,
            base_storage_revision=NULL,base_sha256=NULL,working_data=NULL,
            working_sha256=NULL,metadata=NULL,last_request_id=NULL,last_request_sha256=NULL
        """)
        )
        before = conn.execute(text("SELECT * FROM docx_editor_checkpoints")).all()
    status = api().get_save_status(runtime, handle=pending.handle)
    assert (
        status.state == "superseded" and status.receipt is None and status.checkpoint_revision == 3
    )
    with runtime.engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM docx_editor_checkpoints")).all() == before


def test_claimed_completed_control_does_not_hide_different_working_data(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    key = uuid4()
    finalized = api().finalize_save(runtime, handle=pending.handle, request_id=key)
    other = working(finalized.snapshot.document, "Other ")
    metadata = encode_metadata(
        other["metadata"], data=other["data"], saved_sha256=other["base_sha256"], phase="working"
    )
    from hashlib import sha256

    with runtime.engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE docx_editor_checkpoints SET working_data=:b,working_sha256=:h,
            metadata=CAST(:m AS jsonb)
        """),
            {"b": other["data"], "h": sha256(other["data"]).hexdigest(), "m": json.dumps(metadata)},
        )
        before = conn.execute(text("SELECT * FROM docx_editor_checkpoints")).all()
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=key),
        "storage_error",
        500,
    )
    with runtime.engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM docx_editor_checkpoints")).all() == before


def test_different_control_action_never_confirms_finalize(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    key = uuid4()
    finalized = api().finalize_save(runtime, handle=pending.handle, request_id=key)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_editor_checkpoints SET last_request_sha256=:h"),
            {"h": _control_fingerprint("discard-pending", pending.handle, key)},
        )
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=key),
        "idempotency_conflict",
    )
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=uuid4()),
        "checkpoint_conflict",
    )
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint.working_data
        == finalized.snapshot.checkpoint.working_data
    )


def test_status_scope_and_returned_metadata_remain_isolated(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    result = api().finalize_save(runtime, handle=pending.handle, request_id=uuid4())
    original = deepcopy(result.handle)
    object.__setattr__(pending.handle.metadata.origin, "position_id", 999)
    assert result.handle == original
    reject(
        lambda: api().get_save_status(run_world["runtimes"]["foreign"], handle=result.handle),
        "not_found",
        404,
    )
    status = api().get_save_status(runtime, handle=result.handle)
    object.__setattr__(status.handle.metadata.origin, "position_id", 888)
    assert (
        checkpoints()
        .get_checkpoint(runtime, document_id=item.document_id)
        .checkpoint.metadata.origin.position_id
        == original.metadata.origin.position_id
    )


def test_corrupt_receipt_does_not_clear_pending(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    with runtime.engine.begin() as conn:
        conn.execute(text("UPDATE docx_edit_receipts SET current_size_bytes=current_size_bytes+1"))
    reject(
        lambda: api().finalize_save(runtime, handle=pending.handle, request_id=uuid4()),
        "storage_error",
        500,
    )
    assert (
        checkpoints().get_checkpoint(runtime, document_id=item.document_id).checkpoint
        == pending.snapshot.checkpoint
    )


def test_separate_process_recovers_and_finalizes_pending(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
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
from ara.docx_documents.save_finalize import finalize_save
from ara.docx_package.editor import EditorSession
p=json.load(sys.stdin)
engine=create_engine(p['url'],poolclass=NullPool,hide_parameters=True)
try:
    r=DocumentRuntime(engine=engine,user_id=UUID(p['user']),project_id=UUID(p['project']),mode='local')
    handle=_prepared(get_checkpoint(r,document_id=UUID(p['document']))).handle
    result=finalize_save(r,handle=handle,request_id=uuid4())
    c=result.snapshot.checkpoint
    e=EditorSession.restore(c.working_data,saved_sha256=c.base_sha256,selection=c.metadata.selection)
    print(json.dumps({'checkpoint':c.checkpoint_revision,'phase':c.phase,'base':c.base_storage_revision,
                      'dirty':e.snapshot().document.is_dirty,'current':result.current_matches_receipt}))
finally:engine.dispose()
"""
    root = Path(__file__).resolve().parents[2]
    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env={"PYTHONPATH": str(root / "src")},
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {
        "checkpoint": 3,
        "phase": "working",
        "base": 2,
        "dirty": False,
        "current": True,
    }
    assert (
        api()
        .finalize_save(runtime, handle=pending.handle, request_id=uuid4())
        .snapshot.checkpoint.checkpoint_revision
        == 3
    )


def test_finalize_module_import_is_inert():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy
import hashlib,zipfile,xml.etree.ElementTree,typing,datetime,re
from pathlib import Path
import ara.docx_documents,sqlalchemy,psycopg
assert 'ara.docx_documents.save_finalize' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
    setattr(obj,name,forbidden)
import ara.docx_documents.save_finalize
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
