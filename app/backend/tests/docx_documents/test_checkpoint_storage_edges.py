"""Checkpoint ACK-loss, scope locks, corruption and pending identity boundaries."""

import importlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from ara.docx_documents.checkpoint_fingerprints import pending_fingerprint
from ara.docx_package.checkpoint import encode_metadata
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_checkpoints import api, prepare, put, reject, working
from tests.acceptance.test_docx_recovery import path, request
from tests.acceptance.test_docx_storage_transactions import observe_backend, wait_for_lock
from tests.acceptance.test_docx_text_edit import client, seed

MAX = 9223372036854775807


@pytest.mark.parametrize("after_commit", [False, True])
def test_lost_checkpoint_ack_retries_exactly_once(run_world, monkeypatch, after_commit):
    runtime, item, _ = prepare(run_world)
    values, key = working(item), uuid4()
    real = runtime.engine.dialect.do_commit

    def fail(connection):
        if after_commit:
            real(connection)
        raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: put(runtime, item, request_id=key, **values), "storage_unavailable", 503)
    observed = api().get_checkpoint(runtime, document_id=item.document_id)
    assert observed.checkpoint.checkpoint_revision == (2 if after_commit else 1)
    saved = put(runtime, item, request_id=key, **values)
    assert saved.checkpoint.checkpoint_revision == 2
    assert put(runtime, item, request_id=key, **values) == saved
    assert saved.document == item


def test_invalid_requests_and_frozen_mutation_never_change_durable_copy(run_world):
    runtime, item, empty = prepare(run_world)
    values = working(item)
    for changes in (
        {"expected_checkpoint_revision": True},
        {"request_id": "not a UUID"},
        {"base_storage_revision": True},
        {"base_sha256": "A" * 64},
    ):
        call = dict(
            document_id=item.document_id,
            expected_checkpoint_revision=1,
            request_id=uuid4(),
            **values,
        )
        call.update(changes)
        reject(lambda: api().put_checkpoint(runtime, **call), "validation_error", 422)
    object.__setattr__(values["metadata"].origin, "session_revision", True)
    reject(lambda: put(runtime, item, **values), "invalid_input", 422)
    assert api().get_checkpoint(runtime, document_id=item.document_id) == empty


@pytest.mark.parametrize("corruption", ["hash", "metadata"])
def test_stored_corruption_is_not_cleared_or_reported_as_input_error(run_world, corruption):
    runtime, item, _ = prepare(run_world)
    saved = put(runtime, item, **working(item))
    with runtime.engine.begin() as conn:
        if corruption == "hash":
            conn.execute(
                text("UPDATE docx_editor_checkpoints SET working_sha256=:h"), {"h": "0" * 64}
            )
        else:
            conn.execute(
                text(
                    "UPDATE docx_editor_checkpoints "
                    "SET metadata=jsonb_set(metadata,'{origin,session_revision}','true')"
                )
            )
        before = conn.execute(text("SELECT * FROM docx_editor_checkpoints")).all()
    reject(
        lambda: api().get_checkpoint(runtime, document_id=item.document_id), "storage_error", 500
    )
    reject(
        lambda: api().discard_checkpoint(
            runtime,
            document_id=item.document_id,
            expected_checkpoint_revision=2,
            request_id=uuid4(),
        ),
        "storage_error",
        500,
    )
    with runtime.engine.connect() as conn:
        assert conn.execute(text("SELECT * FROM docx_editor_checkpoints")).all() == before
        assert (
            conn.scalar(
                text("SELECT current_sha256 FROM docx_documents WHERE id=:id"),
                {"id": item.document_id},
            )
            == saved.document.current_sha256
        )


def test_pending_fingerprint_binds_origin_and_revision_without_claiming_commit(run_world):
    runtime, item, _ = prepare(run_world)
    values = working(item)
    put(runtime, item, **values)
    wire = encode_metadata(
        values["metadata"], data=values["data"], saved_sha256=values["base_sha256"], phase="working"
    )
    wire["pending"] = {"operation_id": str(uuid4()), "request_sha256": "0" * 64}
    wire["pending"]["request_sha256"] = pending_fingerprint(
        item.document_id, 3, item.storage_revision, item.current_sha256, values["data"], wire
    )
    with runtime.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE docx_editor_checkpoints "
                "SET phase='pending',checkpoint_revision=3,metadata=CAST(:m AS jsonb)"
            ),
            {"m": json.dumps(wire)},
        )
    pending = api().get_checkpoint(runtime, document_id=item.document_id)
    assert pending.checkpoint.phase == "pending" and pending.document == item
    reject(
        lambda: api().discard_checkpoint(
            runtime,
            document_id=item.document_id,
            expected_checkpoint_revision=3,
            request_id=uuid4(),
        ),
        "pending_save_required",
    )
    with runtime.engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0
        wire["origin"]["session_revision"] = "99"
        conn.execute(
            text("UPDATE docx_editor_checkpoints SET metadata=CAST(:m AS jsonb)"),
            {"m": json.dumps(wire)},
        )
    reject(
        lambda: api().get_checkpoint(runtime, document_id=item.document_id), "storage_error", 500
    )


def test_maximum_revision_allows_replay_but_not_another_transition(run_world):
    runtime, item, _ = prepare(run_world)
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_editor_checkpoints SET checkpoint_revision=:r"), {"r": MAX - 1}
        )
    values, key = working(item), uuid4()
    saved = put(runtime, item, expected=MAX - 1, request_id=key, **values)
    assert saved.checkpoint.checkpoint_revision == MAX
    assert put(runtime, item, expected=MAX - 1, request_id=key, **values) == saved
    reject(
        lambda: api().discard_checkpoint(
            runtime,
            document_id=item.document_id,
            expected_checkpoint_revision=MAX,
            request_id=uuid4(),
        ),
        "revision_exhausted",
    )


def test_legacy_overflow_rolls_back_and_does_not_select_or_parse_word_bytes(run_world, monkeypatch):
    runtime, item, _ = prepare(run_world)
    with client(runtime) as http:
        body = request(http, item)
        with runtime.engine.begin() as conn:
            conn.execute(
                text("UPDATE docx_editor_checkpoints SET checkpoint_revision=:r"), {"r": MAX}
            )
        statements = []

        def observe(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        def forbidden(*args, **kwargs):
            raise AssertionError("Legacy checkpoint must not parse DOCX")

        event.listen(runtime.engine, "before_cursor_execute", observe)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(
                    importlib.import_module("ara.docx_package.projection"),
                    "project_docx",
                    forbidden,
                )
                assert http.get(path(item)).status_code == 200
                response = http.put(path(item), json=body)
                assert (
                    response.status_code == 409 and response.json()["code"] == "revision_exhausted"
                )
        finally:
            event.remove(runtime.engine, "before_cursor_execute", observe)
    assert not any(
        "working_data" in s or "current_data" in s or "original_data" in s for s in statements
    )
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_drafts")) == 0
        assert conn.scalar(text("SELECT checkpoint_revision FROM docx_editor_checkpoints")) == MAX


@pytest.mark.parametrize("change", ["owner", "document"])
def test_scope_change_while_waiting_is_checked_before_checkpoint_access(run_world, change):
    runtime, item, _ = prepare(run_world)
    engine = runtime.engine
    with observe_backend(engine) as (started, backend), ThreadPoolExecutor(max_workers=1) as pool:
        with engine.begin() as blocker:
            if change == "owner":
                blocker.execute(
                    text("SELECT id FROM projects WHERE id=:id FOR UPDATE"),
                    {"id": runtime.project_id},
                )
            else:
                blocker.execute(
                    text("SELECT id FROM docx_documents WHERE id=:id FOR UPDATE"),
                    {"id": item.document_id},
                )
            future = pool.submit(api().get_checkpoint, runtime, document_id=item.document_id)
            wait_for_lock(engine, started, backend)
            if change == "owner":
                blocker.execute(
                    text("UPDATE projects SET owner_id=:owner WHERE id=:id"),
                    {"owner": run_world["owners"]["foreign"], "id": runtime.project_id},
                )
            else:
                blocker.execute(
                    text("UPDATE docx_documents SET project_id=:project WHERE id=:id"),
                    {"project": run_world["projects"]["peer"], "id": item.document_id},
                )
        reject(lambda: future.result(timeout=10), "not_found", 404)


def test_initialization_response_failure_rolls_back_empty_slot(run_world, monkeypatch):
    item = seed(run_world)
    runtime = run_world["runtimes"]["own"]
    dto = importlib.import_module("ara.docx_documents.checkpoint_models")

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic response failure")

    with monkeypatch.context() as patch:
        patch.setattr(dto.CheckpointSnapshot, "__init__", fail)
        reject(
            lambda: api().get_checkpoint(runtime, document_id=item.document_id),
            "storage_error",
            500,
        )
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_editor_checkpoints")) == 0


def test_working_copy_survives_a_separate_process(run_world):
    runtime, item, _ = prepare(run_world)
    saved = put(runtime, item, **working(item))
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
from ara.docx_package.editor import EditorSession
p=json.load(sys.stdin)
engine=create_engine(p['url'],poolclass=NullPool,hide_parameters=True)
try:
    runtime=DocumentRuntime(engine=engine,user_id=UUID(p['user']),
                            project_id=UUID(p['project']),mode='local')
    s=get_checkpoint(runtime,document_id=UUID(p['document']))
    c=s.checkpoint
    restored=EditorSession.restore(c.working_data,saved_sha256=c.base_sha256,
                                  selection=c.metadata.selection).snapshot()
    print(json.dumps({'revision':c.checkpoint_revision,'sha256':c.working_sha256,
                      'dirty':restored.document.is_dirty,'undo':restored.document.undo_depth}))
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
        "revision": 2,
        "sha256": saved.checkpoint.working_sha256,
        "dirty": True,
        "undo": 0,
    }


def test_storage_module_import_has_no_external_side_effects():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys
import hashlib,zipfile,xml.etree.ElementTree,typing,datetime,re
from pathlib import Path
# The existing parent imports SQLAlchemy, whose macOS platform initialization reads files.
# Warm that unchanged dependency, then guard the first import of the new modules.
import ara.docx_documents,sqlalchemy,psycopg
assert 'ara.docx_documents.checkpoints' not in sys.modules
assert 'ara.docx_documents.checkpoint_models' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect')):
    setattr(obj,name,forbidden)
import ara.docx_documents.checkpoints
import ara.docx_documents.checkpoint_models
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
