"""Discard failures preserve data and complete client proof remains replayable."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ara.app import create_app
from ara.docx_documents import get_docx
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world
from tests.acceptance.test_docx_editor_discard_http import discard, prepare_plan
from tests.acceptance.test_docx_editor_downloads import working
from tests.acceptance.test_docx_editor_http import command, control, opened, path, root
from tests.acceptance.test_docx_save_commit import prepared
from tests.acceptance.test_docx_text_edit import seed


@pytest.mark.parametrize("after_commit", [False, True])
def test_real_pending_discard_commit_failure_replays_same_plan(
    run_world, monkeypatch, after_commit
):
    runtime, item, _ = prepared(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        plan, _ = prepare_plan(http, item, 2)
        real = runtime.engine.dialect.do_commit

        def failed(connection):
            if after_commit:
                real(connection)
            raise OperationalError("COMMIT", {}, Exception("PRIVATE"))

        with monkeypatch.context() as patch:
            patch.setattr(runtime.engine.dialect, "do_commit", failed)
            response = discard(http, item, plan)
            assert response.status_code == 503 and "PRIVATE" not in response.text
        with runtime.engine.connect() as conn:
            assert conn.scalar(text("SELECT phase FROM docx_editor_checkpoints")) == (
                "empty" if after_commit else "pending"
            )
        reply = discard(http, item, plan)
        assert reply.status_code == 200 and reply.json()["checkpoint_revision"] == "3"
        assert get_docx(runtime, document_id=item.document_id) == item


def test_working_discard_lost_ack_and_changed_request_identity(run_world, monkeypatch):
    from ara.docx_editor import _discard

    item, runtime = seed(run_world), run_world["runtimes"]["own"]
    with TestClient(create_app(document_runtime=runtime)) as http:
        view, _ = opened(http, item)
        checked = http.post(path(item, view) + "/checkpoint", json=control(view)).json()
        assert checked["checkpoint_revision"] == "2"
        plan, _ = prepare_plan(http, item, 2)
        real = _discard.discard_checkpoint

        def failed(*args, **kwargs):
            real(*args, **kwargs)
            raise OperationalError("ACK", {}, Exception("PRIVATE"))

        with monkeypatch.context() as patch:
            patch.setattr(_discard, "discard_checkpoint", failed)
            response = discard(http, item, plan)
            assert response.status_code == 500 and "PRIVATE" not in response.text
        assert discard(http, item, plan).status_code == 200
        changed = {**plan, "request_id": str(uuid4())}
        assert discard(http, item, changed).status_code == 409
        assert get_docx(runtime, document_id=item.document_id) == item


def test_pending_discard_leaves_live_actor_conflicted_but_rescuable(run_world):
    runtime, item, pending = prepared(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        view, _ = opened(http, item, mode="recover")
        plan, _ = prepare_plan(http, item, 2)
        assert discard(http, item, plan).status_code == 200
        assert http.get(path(item, view)).json()["state"] == "conflict"
        assert (
            http.post(
                path(item, view) + "/commands", json=command(view, "insert_text", "No ")
            ).status_code
            == 409
        )
        rescue = http.post(path(item, view) + "/working-content", json=working(view))
        assert (
            rescue.status_code == 200 and rescue.content == pending.snapshot.checkpoint.working_data
        )


def test_passive_plan_commit_failure_does_not_return_plan_or_write(run_world, monkeypatch):
    runtime, item, _ = prepared(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:

        def failed(connection):
            raise OperationalError("COMMIT", {}, Exception("PRIVATE"))

        request = dict(expected_checkpoint_revision="2", request_id=str(uuid4()))
        with monkeypatch.context() as patch:
            patch.setattr(runtime.engine.dialect, "do_commit", failed)
            response = http.post(root(item) + "/editor-recovery/prepare-discard", json=request)
            assert response.status_code == 503 and "handle" not in response.json()
        assert (
            http.post(root(item) + "/editor-recovery/prepare-discard", json=request).status_code
            == 200
        )
        with runtime.engine.connect() as conn:
            assert conn.scalar(text("SELECT phase FROM docx_editor_checkpoints")) == "pending"


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_complete_valid_plan_cannot_cross_runtime_scope(run_world, scope):
    runtime, item, _ = prepared(run_world)
    with TestClient(create_app(document_runtime=runtime)) as http:
        plan, _ = prepare_plan(http, item, 2)
    with TestClient(create_app(document_runtime=run_world["runtimes"][scope])) as other:
        response = discard(other, item, plan)
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT phase FROM docx_editor_checkpoints")) == "pending"


def test_inert_install_and_all_schema_references_resolve(run_world):
    from ara.config import ConfigurationError
    from ara.docx_editor.http_discard import install_editor_discard

    with pytest.raises(ConfigurationError):
        install_editor_discard(create_app())
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    with pytest.raises(ConfigurationError):
        install_editor_discard(app)
    with TestClient(app) as http:
        schema = http.get("/openapi.json").json()

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                target = schema
                for part in value["$ref"].split("/")[1:]:
                    target = target[part]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)
