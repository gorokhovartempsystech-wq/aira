"""Frozen D03-16B2B: durable working copies, CAS and legacy fences."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from test_docx_recovery import path, request
from test_docx_text_edit import client, seed

from ara.documents.storage import DocumentError
from ara.docx_documents import get_docx, save_docx
from ara.docx_package.checkpoint import CheckpointMetadata, CheckpointOrigin
from ara.docx_package.editor import EditorSession


def api():
    return importlib.import_module("ara.docx_documents.checkpoints")


def working(item, text="Working "):
    s = EditorSession(item.current_data).insert_text(text, expected_revision=0)
    return {
        "base_storage_revision": item.storage_revision,
        "base_sha256": item.current_sha256,
        "data": s.document.data,
        "metadata": CheckpointMetadata(s.selection, CheckpointOrigin(uuid4(), 1, s.position_id)),
    }


def prepare(world):
    item = seed(world)
    runtime = world["runtimes"]["own"]
    empty = api().get_checkpoint(runtime, document_id=item.document_id)
    assert empty.checkpoint.phase == "empty" and empty.checkpoint.checkpoint_revision == 1
    return runtime, item, empty


def put(runtime, item, expected=1, request_id=None, **values):
    return api().put_checkpoint(
        runtime,
        document_id=item.document_id,
        expected_checkpoint_revision=expected,
        request_id=request_id or uuid4(),
        **values,
    )


def reject(call, code, status=409):
    with pytest.raises(DocumentError) as caught:
        call()
    assert (caught.value.status, caught.value.code) == (status, code)


def test_full_working_copy_reopens_without_changing_saved_document(run_world):
    runtime, item, empty = prepare(run_world)
    assert api().get_checkpoint(runtime, document_id=item.document_id) == empty
    values = working(item)
    saved = put(runtime, item, **values)
    c = saved.checkpoint
    assert c.phase == "working" and c.checkpoint_revision == 2 and c.format_version == 1
    assert c.working_data == values["data"] and c.metadata == values["metadata"]
    assert saved.document == get_docx(runtime, document_id=item.document_id)
    assert saved.document == empty.document
    restored = EditorSession.restore(
        c.working_data, saved_sha256=c.base_sha256, selection=c.metadata.selection
    )
    assert restored.snapshot().document.is_dirty
    assert restored.snapshot().document.undo_depth == 0
    engine = create_engine(run_world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        assert (
            api().get_checkpoint(replace(runtime, engine=engine), document_id=item.document_id)
            == saved
        )
    finally:
        engine.dispose()


def test_replay_altered_body_discard_and_empty_tombstone_aba(run_world):
    runtime, item, _ = prepare(run_world)
    values, key = working(item), uuid4()
    saved = put(runtime, item, request_id=key, **values)
    assert put(runtime, item, request_id=key, **values) == saved
    reject(
        lambda: put(runtime, item, request_id=key, **working(item, "Other ")),
        "idempotency_conflict",
    )
    discard_id = uuid4()
    empty = api().discard_checkpoint(
        runtime, document_id=item.document_id, expected_checkpoint_revision=2, request_id=discard_id
    )
    assert empty.checkpoint.phase == "empty" and empty.checkpoint.checkpoint_revision == 3
    assert empty.checkpoint.working_data is None and empty.checkpoint.metadata is None
    assert (
        api().discard_checkpoint(
            runtime,
            document_id=item.document_id,
            expected_checkpoint_revision=2,
            request_id=discard_id,
        )
        == empty
    )
    reject(lambda: put(runtime, item, request_id=key, **values), "checkpoint_conflict")
    reject(lambda: put(runtime, item, expected=1, **values), "checkpoint_conflict")
    assert put(runtime, item, expected=3, **values).checkpoint.checkpoint_revision == 4


def test_two_windows_cannot_overwrite_each_other(run_world):
    runtime, item, _ = prepare(run_world)
    barrier = Barrier(2)

    def writer(label):
        values = working(item, label)
        barrier.wait(timeout=5)
        try:
            return put(runtime, item, **values)
        except DocumentError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, ("First ", "Second ")))
    errors = [r for r in results if isinstance(r, DocumentError)]
    winners = [r for r in results if not isinstance(r, DocumentError)]
    assert len(winners) == len(errors) == 1 and errors[0].code == "checkpoint_conflict"
    assert api().get_checkpoint(runtime, document_id=item.document_id) == winners[0]


def test_foreign_current_revision_conflicts_even_when_bytes_are_equal(run_world):
    runtime, item, _ = prepare(run_world)
    values = working(item)
    original = put(runtime, item, **values)
    save_docx(
        runtime,
        document_id=item.document_id,
        expected_storage_revision=item.storage_revision,
        data=item.current_data,
    )
    reject(lambda: put(runtime, item, expected=2, **values), "docx_conflict")
    latest = api().get_checkpoint(runtime, document_id=item.document_id)
    assert latest.checkpoint == original.checkpoint
    assert latest.document.storage_revision == item.storage_revision + 1


def test_legacy_draft_blocks_new_slot_and_new_work_blocks_legacy(run_world):
    item = seed(run_world)
    runtime = run_world["runtimes"]["own"]
    with client(runtime) as http:
        body = request(http, item)
        assert http.put(path(item), json=body).status_code == 200
        reject(
            lambda: api().get_checkpoint(runtime, document_id=item.document_id),
            "legacy_draft_present",
        )
        assert (
            http.request("DELETE", path(item), json={"expected_token": body["token"]}).status_code
            == 204
        )
        empty = api().get_checkpoint(runtime, document_id=item.document_id)
        assert empty.checkpoint.checkpoint_revision == 1
        assert http.put(path(item), json=body).status_code == 200
        assert http.put(path(item), json=body).status_code == 200
        assert (
            http.request("DELETE", path(item), json={"expected_token": body["token"]}).status_code
            == 204
        )
        fenced = api().get_checkpoint(runtime, document_id=item.document_id)
        assert fenced.checkpoint.checkpoint_revision == 2
        reject(lambda: put(runtime, item, **working(item)), "checkpoint_conflict")
        put(runtime, item, expected=2, **working(item))
        for response in (
            http.get(path(item)),
            http.put(path(item), json=body),
            http.request("DELETE", path(item), json={"expected_token": body["token"]}),
        ):
            assert response.status_code == 409 and response.json()["code"] == "draft_mode_conflict"


def test_scope_is_checked_before_any_checkpoint_conflict(run_world):
    runtime, item, _ = prepare(run_world)
    put(runtime, item, **working(item))
    for other in (run_world["runtimes"]["peer"], run_world["runtimes"]["foreign"]):
        reject(lambda: api().get_checkpoint(other, document_id=item.document_id), "not_found", 404)
        reject(
            lambda: api().discard_checkpoint(
                other,
                document_id=item.document_id,
                expected_checkpoint_revision=1,
                request_id=uuid4(),
            ),
            "not_found",
            404,
        )


def test_reply_failure_rolls_back_and_snapshots_are_detached(run_world, monkeypatch):
    runtime, item, empty = prepare(run_world)
    dto = importlib.import_module("ara.docx_documents.checkpoint_models")
    values = working(item)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic response failure")

    with monkeypatch.context() as patch:
        patch.setattr(dto.CheckpointSnapshot, "__init__", fail)
        reject(lambda: put(runtime, item, **values), "storage_error", 500)
    assert api().get_checkpoint(runtime, document_id=item.document_id) == empty
    saved = put(runtime, item, **values)
    object.__setattr__(saved.checkpoint.metadata.origin, "session_revision", 999)
    assert (
        api()
        .get_checkpoint(runtime, document_id=item.document_id)
        .checkpoint.metadata.origin.session_revision
        == 1
    )
    with run_world["engine"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_edit_receipts")) == 0
