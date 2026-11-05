"""Registry failure cuts, passive proof changes, retained objects and process epochs."""

import importlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ara.docx_documents import get_docx
from ara.docx_documents._dto import MAX_REVISION
from ara.docx_documents.save_commit import commit_save
from ara.docx_documents.save_reconcile import reconcile_save
from ara.docx_package.editor import Caret, EditorSelection, EditorSession
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.docx_projection_fixtures import package
from tests.acceptance.test_docx_checkpoints import api as checkpoints
from tests.acceptance.test_docx_checkpoints import prepare, put, reject, working
from tests.acceptance.test_docx_editor_registry import api, opening
from tests.acceptance.test_docx_save_commit import prepared
from tests.acceptance.test_docx_text_edit import seed


@pytest.mark.parametrize("after_commit", [False, True])
def test_failure_at_final_read_commit_releases_admission(run_world, monkeypatch, after_commit):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    real, calls = runtime.engine.dialect.do_commit, 0

    def fail(conn):
        nonlocal calls
        calls += 1
        if calls == 2:
            if after_commit:
                real(conn)
            raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))
        real(conn)

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: registry.open(**request), "storage_unavailable", 503)
    assert registry._budget.groups == {} and not registry._actors and not registry._opens
    assert registry.inspect_recovery(document_id=item.document_id).open_sequence == 0
    assert registry.open(**request).next_open_sequence == 1


def test_live_pending_observes_commit_then_superseded_checkpoint_without_mutating(run_world):
    runtime, item, pending = prepared(run_world)
    registry = api().EditorRegistry(runtime)
    view = registry.open(**opening(registry, item, mode="recover")).view
    commit_save(runtime, handle=pending.handle)
    assert (
        registry.snapshot(document_id=item.document_id, session_id=view.session_id).state
        == "recovery_pending"
    )
    final = reconcile_save(runtime, handle=pending.handle, request_id=uuid4())
    observed = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert observed.state == "conflict" and observed.editor == view.editor
    assert observed.recovery_operation_id == pending.handle.operation_id
    assert checkpoints().get_checkpoint(runtime, document_id=item.document_id) == final.snapshot


def test_two_live_copies_detect_fence_even_without_head_change(run_world):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    view = registry.open(**opening(registry, item)).view
    put(runtime, item, **working(item, ""))
    observed = registry.snapshot(document_id=item.document_id, session_id=view.session_id)
    assert observed.state == "conflict" and not observed.editor.document.is_dirty
    assert observed.observed_current.storage_revision == 1
    assert observed.checkpoint_revision == 1 and observed.observed_checkpoint_revision == 2


def test_reverse_selection_restart_and_inspection_detached(run_world):
    runtime, item, _ = prepare(run_world)
    values = working(item)
    selection = values["metadata"].selection
    end = Caret(selection.anchor.anchor, 2, "left")
    metadata = replace(values["metadata"], selection=EditorSelection(selection.anchor, end))
    put(runtime, item, **{**values, "metadata": metadata})
    registry = api().EditorRegistry(runtime)
    observed = registry.inspect_recovery(document_id=item.document_id)
    object.__setattr__(observed.origin, "position_id", 999)
    object.__setattr__(observed.selection.focus, "offset", 999)
    restored = registry.open(**opening(registry, item, mode="recover")).view
    assert restored.editor.selection == metadata.selection
    assert restored.editor.selection.anchor.offset > restored.editor.selection.focus.offset


def test_open_at_max_and_resource_replay_stays_available(run_world):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    view = registry.open(**request).view
    registry._open_sequence = MAX_REVISION
    assert registry.open(**request).next_open_sequence == MAX_REVISION
    assert registry.snapshot(document_id=item.document_id, session_id=view.session_id) == view
    reject(lambda: registry.open(**opening(registry, item)), "revision_exhausted")


def test_package_budget_counts_identity_and_reserves_both_live_and_candidate():
    from ara.docx_editor._budget import PackageBudget

    a, b = b"ABC", bytes(bytearray(b"ABC"))
    assert a == b and a is not b
    budget = PackageBudget(3)
    budget.reserve("live", (a, a))
    budget.reserve("candidate", (a,))
    reject(lambda: budget.reserve("other", (b,)), "editor_limit_exceeded", 413)
    assert set(budget.groups) == {"live", "candidate"}
    budget.release("live")
    reject(lambda: budget.reserve("other", (b,)), "editor_limit_exceeded", 413)
    budget.release("candidate")
    budget.reserve("other", (b,))


def test_retained_references_cover_real_core_history_without_mutation():
    from tests.acceptance.docx_storage_fixtures import raw

    editor = EditorSession(raw("Device"))
    first = editor.snapshot()
    second = editor.insert_text("One ", expected_revision=0)
    third = editor.insert_text("Two ", expected_revision=1)
    editor.undo(expected_revision=2)
    before = editor.snapshot()
    retained = editor._retained_packages()
    assert all(type(data) is bytes for data in retained)
    assert {id(data) for data in retained} == {id(s.document.data) for s in (first, second, third)}
    assert editor.snapshot() == before
    assert editor.redo(expected_revision=3).document.data == third.document.data


def test_valid_package_without_body_paragraph_is_preserved_and_rejected(run_world):
    data = package(
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )[0]
    item = seed(run_world, data)
    registry = api().EditorRegistry(run_world["runtimes"]["own"])
    reject(lambda: registry.open(**opening(registry, item)), "editor_document_unsupported", 422)
    assert registry.inspect_recovery(document_id=item.document_id).open_sequence == 0
    assert get_docx(run_world["runtimes"]["own"], document_id=item.document_id).current_data == data


def test_corrupt_checkpoint_and_foreign_receipt_remain_untouched(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    with runtime.engine.begin() as conn:
        conn.execute(text("UPDATE docx_edit_receipts SET request_sha256=:hash"), {"hash": "f" * 64})
    registry = api().EditorRegistry(runtime)
    reject(lambda: registry.inspect_recovery(document_id=item.document_id), "idempotency_conflict")
    with runtime.engine.begin() as conn:
        conn.execute(text("DELETE FROM docx_edit_receipts"))
        conn.execute(
            text("UPDATE docx_editor_checkpoints SET working_sha256=:hash"), {"hash": "f" * 64}
        )
    reject(lambda: registry.inspect_recovery(document_id=item.document_id), "storage_error", 500)
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT checkpoint_revision FROM docx_editor_checkpoints")) == 2


def test_scope_move_and_altered_document_do_not_leak_session(run_world):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    view = registry.open(**request).view
    second = seed(run_world)
    reject(
        lambda: registry.open(**{**request, "document_id": second.document_id}),
        "idempotency_conflict",
    )
    with runtime.engine.begin() as conn:
        conn.execute(
            text("UPDATE docx_documents SET project_id=:project WHERE id=:id"),
            {"project": run_world["projects"]["peer"], "id": item.document_id},
        )
    reject(
        lambda: registry.snapshot(document_id=item.document_id, session_id=view.session_id),
        "not_found",
        404,
    )
    reject(lambda: registry.open(**request), "not_found", 404)


def test_new_dto_validation_and_sanitized_reply_failure(run_world, monkeypatch):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    result = registry.open(**opening(registry, item))
    damaged = deepcopy(result)
    object.__setattr__(damaged.view.editor.document, "is_dirty", 0)
    with pytest.raises(ValueError):
        damaged.__post_init__()
    model = importlib.import_module("ara.docx_editor._models")

    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE")

    with monkeypatch.context() as patch:
        patch.setattr(model.EditorView, "__post_init__", fail)
        from ara.documents.storage import DocumentError

        with pytest.raises(DocumentError) as caught:
            registry.snapshot(document_id=item.document_id, session_id=result.view.session_id)
        assert caught.value.code == "editor_error" and "SYNTHETIC_PRIVATE" not in str(caught.value)
    assert (
        registry.snapshot(document_id=item.document_id, session_id=result.view.session_id)
        == result.view
    )


def test_separate_process_restores_new_registry_and_session(run_world):
    runtime, item, _ = prepare(run_world)
    values = working(item)
    put(runtime, item, **values)
    registry = api().EditorRegistry(runtime)
    view = registry.open(**opening(registry, item, mode="recover")).view
    payload = {
        "url": runtime.engine.url.render_as_string(hide_password=False),
        "user": str(runtime.user_id),
        "project": str(runtime.project_id),
        "doc": str(item.document_id),
    }
    script = """
import json,sys,hashlib
from uuid import UUID,uuid4
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ara.documents.runtime import DocumentRuntime
from ara.docx_editor import EditorRegistry
p=json.load(sys.stdin);engine=create_engine(p['url'],poolclass=NullPool,hide_parameters=True)
try:
 r=EditorRegistry(DocumentRuntime(engine=engine,user_id=UUID(p['user']),project_id=UUID(p['project']),mode='local'))
 d=UUID(p['doc']);s=r.inspect_recovery(document_id=d)
 v=r.open(document_id=d,registry_id=s.registry_id,client_open_id=uuid4(),expected_open_sequence=s.open_sequence,expected_checkpoint_revision=s.checkpoint_revision,mode='recover').view
 print(json.dumps({'registry':str(v.registry_id),'session':str(v.session_id),'dirty':v.editor.document.is_dirty,'revision':v.editor.document.revision,'undo':v.editor.document.undo_depth,'hash':hashlib.sha256(v.editor.document.data).hexdigest()}))
finally:engine.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(payload),
        env={"PYTHONPATH": str(Path.cwd() / "src")},
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["registry"] != str(view.registry_id) and observed["session"] != str(
        view.session_id
    )
    assert observed["dirty"] and observed["revision"] == observed["undo"] == 0
    from hashlib import sha256

    assert observed["hash"] == sha256(values["data"]).hexdigest()


def test_first_import_and_constructor_are_inert():
    script = """
import builtins,io,os,socket,subprocess,logging,json,dataclasses,uuid,sys,copy,contextlib,functools
import hashlib,re,zipfile,xml.etree.ElementTree,typing,datetime,threading
from pathlib import Path
import sqlalchemy,psycopg
from uuid import uuid4
from ara.documents.runtime import DocumentRuntime
engine=sqlalchemy.create_engine('postgresql+psycopg://localhost/unused',hide_parameters=True)
runtime=DocumentRuntime(engine=engine,user_id=uuid4(),project_id=uuid4(),mode='local')
assert 'ara.docx_editor' not in sys.modules
def forbidden(*args,**kwargs):raise AssertionError('External I/O')
for obj,name in ((builtins,'open'),(io,'open'),(os,'getenv'),(socket,'socket'),
                 (subprocess,'Popen'),(logging.Logger,'_log'),(Path,'read_bytes'),
                 (sqlalchemy,'create_engine'),(psycopg,'connect'),(engine,'connect')):
 setattr(obj,name,forbidden)
from ara.docx_editor import EditorRegistry
EditorRegistry(runtime)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={"PYTHONPATH": str(Path.cwd() / "src")},
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout


def test_unknown_and_missing_python_request_fields_are_input_errors(run_world):
    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    reject(
        lambda: registry.open(**request, unexpected="SYNTHETIC_PRIVATE"), "validation_error", 422
    )
    del request["mode"]
    reject(lambda: registry.open(**request), "validation_error", 422)
    assert registry.inspect_recovery(document_id=item.document_id).open_sequence == 0


@pytest.mark.parametrize("after_commit", [False, True])
def test_initial_empty_slot_ack_loss_does_not_publish_or_reset_counter(
    run_world, monkeypatch, after_commit
):
    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    assert request["expected_checkpoint_revision"] == 0
    real, count = runtime.engine.dialect.do_commit, 0

    def fail(conn):
        nonlocal count
        count += 1
        if count == 2:
            if after_commit:
                real(conn)
            raise OperationalError("SYNTHETIC_PRIVATE", {}, RuntimeError("SYNTHETIC_PRIVATE"))
        real(conn)

    with monkeypatch.context() as patch:
        patch.setattr(runtime.engine.dialect, "do_commit", fail)
        reject(lambda: registry.open(**request), "storage_unavailable", 503)
    observed = registry.inspect_recovery(document_id=item.document_id)
    assert observed.open_sequence == 0 and observed.checkpoint_revision == int(after_commit)
    assert registry.open(**request).next_open_sequence == 1
    assert get_docx(runtime, document_id=item.document_id) == item


def test_legacy_draft_prevents_open_without_initializing_slot(run_world):
    from tests.acceptance.test_docx_recovery import request
    from tests.acceptance.test_docx_text_edit import client

    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    registry = api().EditorRegistry(runtime)
    attempt = opening(registry, item)
    with client(runtime) as http:
        payload = request(http, item)
        response = http.put(f"/docx-documents/{item.document_id}/draft", json=payload)
        assert response.status_code == 200
    reject(lambda: registry.open(**attempt), "legacy_draft_present")
    reject(lambda: registry.inspect_recovery(document_id=item.document_id), "legacy_draft_present")
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_editor_checkpoints")) == 0
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_drafts")) == 1


def test_open_replay_rechecks_scope_after_waiting_for_actor(run_world, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event

    runtime, item, _ = prepare(run_world)
    registry = api().EditorRegistry(runtime)
    request = opening(registry, item)
    view = registry.open(**request).view
    actor = registry._actors[(item.document_id, view.session_id)]
    module = importlib.import_module("ara.docx_editor._registry")
    real, passed = module.observe, Event()

    @contextmanager
    def observe(*args, **kwargs):
        with real(*args, **kwargs) as observation:
            yield observation
        passed.set()

    monkeypatch.setattr(module, "observe", observe)
    actor.mutex.acquire()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(registry.open, **request)
        try:
            assert passed.wait(5)
            with runtime.engine.begin() as conn:
                conn.execute(
                    text("UPDATE projects SET owner_id=:u WHERE id=:p"),
                    {"u": run_world["owners"]["foreign"], "p": runtime.project_id},
                )
        finally:
            actor.mutex.release()
        reject(lambda: future.result(timeout=10), "not_found", 404)
