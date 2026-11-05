"""Frozen E3B: client-retained exact discard plans survive ACK loss/restart."""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_docx_checkpoints import put
from test_docx_checkpoints import working as working_copy
from test_docx_editor_downloads import working
from test_docx_editor_http import command, control, opened, path, root
from test_docx_save_commit import prepared
from test_docx_text_edit import seed

from ara.app import create_app
from ara.documents.storage import DocumentError
from ara.docx_documents import get_docx, save_docx
from ara.docx_documents.save_commit import commit_save


def prepare_plan(http, item, revision):
    request = dict(expected_checkpoint_revision=str(revision), request_id=str(uuid4()))
    response = http.post(root(item) + "/editor-recovery/prepare-discard", json=request)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json(), request


def discard(http, item, plan):
    return http.post(root(item) + "/editor-recovery/discard", json=plan)


def test_working_plan_passive_discard_repeat_restart_and_live_ram_preserved(run_world):
    runtime, item = run_world["runtimes"]["own"], seed(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        view, _ = opened(http, item)
        edited = http.post(
            path(item, view) + "/commands", json=command(view, "insert_text", "Draft ")
        ).json()
        saved = http.post(path(item, view) + "/checkpoint", json=control(edited)).json()
        plan, request = prepare_plan(http, item, 2)
        assert plan == dict(kind="working", document_id=str(item.document_id), **request)
        assert (
            http.post(root(item) + "/editor-recovery/prepare-discard", json=request).json() == plan
        )
        with runtime.engine.connect() as conn:
            assert conn.execute(
                text("SELECT phase, checkpoint_revision FROM docx_editor_checkpoints")
            ).one() == ("working", 2)
        result = discard(http, item, plan)
        assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
        reply = result.json()
        assert reply["kind"] == "discarded" and reply["checkpoint_revision"] == "3"
        assert (
            reply["save_confirmation"] == "not_checked" and reply["current_matches_receipt"] is None
        )
        assert http.get(path(item, view)).json()["state"] == "conflict"
        rescue = http.post(path(item, view) + "/working-content", json=working(saved))
        assert rescue.status_code == 200 and rescue.content != item.current_data
        assert discard(http, item, plan).json() == reply
    with TestClient(create_app(document_runtime=runtime)) as restarted:
        assert discard(restarted, item, plan).json() == reply
    assert get_docx(runtime, document_id=item.document_id) == item
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT metadata IS NULL FROM docx_editor_checkpoints"))


@pytest.mark.parametrize("head", ["uncommitted", "committed", "newer"])
def test_pending_plan_preserves_current_and_receipt_with_exact_replay(run_world, head):
    runtime, item, pending = prepared(run_world)
    if head != "uncommitted":
        saved = commit_save(runtime, handle=pending.handle)
        if head == "newer":
            save_docx(
                runtime,
                document_id=item.document_id,
                expected_storage_revision=2,
                data=item.current_data,
            )
        else:
            assert saved.document.storage_revision == 2
    before = get_docx(runtime, document_id=item.document_id)
    with TestClient(create_app(document_runtime=runtime)) as http:
        plan, _ = prepare_plan(http, item, 2)
        assert plan["kind"] == "pending" and "data" not in plan
        assert plan["handle"]["metadata"]["pending"]["operation_id"] == str(
            pending.handle.operation_id
        )
        assert plan["handle"]["prepared_checkpoint_revision"] == "2"
        result = discard(http, item, plan)
        assert result.status_code == 200, result.text
        reply = result.json()
        assert reply["save_confirmation"] == (
            "unconfirmed" if head == "uncommitted" else "confirmed"
        )
        assert reply["current_matches_receipt"] == (head == "committed")
        assert reply["current"]["storage_revision"] == str(before.storage_revision)
        assert discard(http, item, plan).json() == reply
    with TestClient(create_app(document_runtime=runtime)) as restarted:
        assert discard(restarted, item, plan).json() == reply
    assert get_docx(runtime, document_id=item.document_id) == before


def test_old_discard_plan_never_clears_a_newer_working_copy(run_world):
    runtime, item, _ = prepared(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        plan, _ = prepare_plan(http, item, 2)
        assert discard(http, item, plan).status_code == 200
        newer = put(runtime, item, expected=3, **working_copy(item, "Newer "))
        assert discard(http, item, plan).status_code == 409
        assert (
            http.post(
                root(item) + "/editor-recovery/prepare-discard",
                json=dict(expected_checkpoint_revision="2", request_id=str(uuid4())),
            ).status_code
            == 409
        )
    with runtime.engine.connect() as conn:
        assert (
            conn.scalar(text("SELECT working_data FROM docx_editor_checkpoints"))
            == newer.checkpoint.working_data
        )


def test_lost_ack_after_pending_clear_replays_retained_plan_in_new_app(run_world, monkeypatch):
    from ara.docx_editor import _discard

    runtime, item, _ = prepared(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        plan, _ = prepare_plan(http, item, 2)
        real = _discard.discard_pending

        def lost(*args, **kwargs):
            real(*args, **kwargs)
            raise DocumentError(503, "storage_unavailable", "Unavailable", True)

        with monkeypatch.context() as patch:
            patch.setattr(_discard, "discard_pending", lost)
            assert discard(http, item, plan).status_code == 503
    with TestClient(create_app(document_runtime=runtime)) as restarted:
        reply = discard(restarted, item, plan)
        assert reply.status_code == 200 and reply.json()["checkpoint_revision"] == "3"
        assert reply.json()["save_confirmation"] == "unconfirmed"
    assert get_docx(runtime, document_id=item.document_id) == item


def test_malformed_or_substituted_complete_plan_rejected_before_storage(run_world, monkeypatch):
    from ara.docx_editor import _discard

    runtime, item, _ = prepared(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        plan, _ = prepare_plan(http, item, 2)

        def forbidden(*args, **kwargs):
            raise AssertionError("Invalid plan dispatched")

        monkeypatch.setattr(_discard, "discard_pending", forbidden)
        cases = []
        bad = deepcopy(plan)
        bad["handle"]["working_sha256"] = "0" * 64
        cases.append(bad)
        bad = deepcopy(plan)
        bad["handle"]["metadata"]["origin"]["session_revision"] = 1
        cases.append(bad)
        bad = deepcopy(plan)
        bad["handle"]["document_id"] = str(uuid4())
        cases.append(bad)
        bad = deepcopy(plan)
        bad["document_id"] = str(uuid4())
        cases.append(bad)
        bad = deepcopy(plan)
        bad["handle"]["data"] = "PRIVATE"
        cases.append(bad)
        for bad in cases:
            response = discard(http, item, bad)
            assert response.status_code == 422 and "PRIVATE" not in response.text
    assert get_docx(runtime, document_id=item.document_id) == item


def test_prepare_ignores_corrupt_receipt_but_discard_does_not_clear_it(run_world):
    runtime, item, pending = prepared(run_world)
    commit_save(runtime, handle=pending.handle)
    with runtime.engine.begin() as conn:
        conn.execute(text("UPDATE docx_edit_receipts SET current_size_bytes=current_size_bytes+1"))
    with TestClient(create_app(document_runtime=runtime)) as http:
        plan, _ = prepare_plan(http, item, 2)
        response = discard(http, item, plan)
        assert response.status_code == 500
        recovery = http.post(
            root(item) + "/editor-recovery/content",
            json=dict(
                expected_checkpoint_revision="2", expected_sha256=pending.handle.working_sha256
            ),
        )
        assert (
            recovery.status_code == 200
            and recovery.content == pending.snapshot.checkpoint.working_data
        )
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT phase FROM docx_editor_checkpoints")) == "pending"


def test_absent_empty_foreign_and_openapi_discard_boundaries(run_world):
    runtime, item = run_world["runtimes"]["own"], seed(run_world)
    request = dict(expected_checkpoint_revision="0", request_id=str(uuid4()))
    with TestClient(create_app(document_runtime=runtime)) as http:
        assert (
            http.post(root(item) + "/editor-recovery/prepare-discard", json=request).status_code
            == 409
        )
        with runtime.engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM docx_editor_checkpoints")) == 0
        view, _ = opened(http, item)
        assert view["checkpoint_revision"] == "1"
        assert (
            http.post(
                root(item) + "/editor-recovery/prepare-discard",
                json={**request, "expected_checkpoint_revision": "1"},
            ).status_code
            == 409
        )
        schema = http.get("/openapi.json").json()
        for action in ("prepare-discard", "discard"):
            endpoint = schema["paths"]["/docx-documents/{document_id}/editor-recovery/" + action][
                "post"
            ]
            assert endpoint["requestBody"]["required"] is True
            assert "409" in endpoint["responses"] and "503" in endpoint["responses"]
    with TestClient(create_app(document_runtime=run_world["runtimes"]["foreign"])) as foreign:
        response = foreign.post(root(item) + "/editor-recovery/prepare-discard", json=request)
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
