"""Frozen E2: bounded scoped JSON routes and per-application editor lifetime."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_docx_text_edit import seed

from ara.app import create_app
from ara.docx_documents import get_docx


def root(item):
    return f"/docx-documents/{item.document_id}"


def opened(http, item, mode="current"):
    response = http.get(root(item) + "/editor-recovery")
    assert response.status_code == 200, response.text
    status = response.json()
    request = dict(
        registry_id=status["registry_id"],
        client_open_id=str(uuid4()),
        expected_open_sequence=status["open_sequence"],
        expected_checkpoint_revision=status["checkpoint_revision"],
        mode=mode,
    )
    response = http.post(root(item) + "/editor-sessions", json=request)
    assert response.status_code == 200, response.text
    return response.json()["view"], request


def path(item, view):
    return root(item) + "/editor-sessions/" + view["session_id"]


def control(view):
    return dict(
        command_id=str(uuid4()),
        expected_command_sequence=view["command_sequence"],
        expected_session_revision=view["document"]["session_revision"],
    )


def command(view, action, value=None):
    return {**control(view), "command": dict(action=action, value=value)}


def test_http_complete_save_close_restore_and_exact_replay(run_world):
    runtime, item = run_world["runtimes"]["own"], seed(run_world)
    app = create_app(document_runtime=runtime)
    with TestClient(app) as http:
        view, request = opened(http, item)
        assert "blocks" not in view and "data" not in view["document"]
        assert http.post(root(item) + "/editor-sessions", json=request).json()["view"] == view
        body = command(view, "insert_text", "New 🧪 ")
        response = http.post(path(item, view) + "/commands", json=body)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        edited = response.json()
        assert edited["command_sequence"] == "1" and edited["document"]["is_dirty"] is True
        assert http.post(path(item, view) + "/commands", json=body).json() == edited
        full = http.get(path(item, view) + "/view").json()
        assert full["view"] == edited and full["projection"]["blocks"][0]["text"].startswith(
            "New 🧪 Device"
        )
        body = control(edited)
        saved = http.post(path(item, view) + "/save", json=body).json()
        assert saved["document"]["is_dirty"] is False and saved["base_storage_revision"] == "2"
        assert http.post(path(item, view) + "/save", json=body).json() == saved
        assert http.post(path(item, view) + "/reconcile", json=body).json() == saved
        closed = http.post(path(item, view) + "/close", json=control(saved))
        assert closed.status_code == 200 and closed.json()["kind"] == "closed"
        assert http.get(path(item, view)).status_code == 410
        restored, _ = opened(http, item, mode="recover")
        assert restored["session_id"] != view["session_id"] and not restored["document"]["is_dirty"]
        assert (
            restored["document"]["session_revision"] == "0"
            and restored["document"]["undo_depth"] == 0
        )
    current = get_docx(runtime, document_id=item.document_id)
    assert current.storage_revision == 2 and current.original_data == item.original_data


def test_new_app_epoch_and_foreign_scope_do_not_reuse_session(run_world):
    item = seed(run_world)
    with TestClient(create_app(document_runtime=run_world["runtimes"]["own"])) as first:
        view, request = opened(first, item)
    with TestClient(create_app(document_runtime=run_world["runtimes"]["own"])) as second:
        assert second.get(path(item, view)).status_code == 410
        assert second.post(root(item) + "/editor-sessions", json=request).status_code == 410
        again, _ = opened(second, item)
        assert again["registry_id"] != view["registry_id"]
    with TestClient(create_app(document_runtime=run_world["runtimes"]["foreign"])) as foreign:
        response = foreign.get(path(item, view))
        assert response.status_code == 404 and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "kind", ["duplicate", "nan", "unknown", "bad_utf8", "noncanonical", "query"]
)
def test_bad_commands_are_rejected_before_dispatch(run_world, monkeypatch, kind):
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    with TestClient(app) as http:
        view, _ = opened(http, item)
        body = command(view, "insert_text", "SYNTHETIC_PRIVATE")
        target = path(item, view) + "/commands"
        if kind == "duplicate":
            raw = (
                json.dumps(body)
                .replace('"action": "insert_text"', '"action":"undo","action":"insert_text"')
                .encode()
            )
        elif kind == "nan":
            raw = json.dumps(body).replace('"0"', "NaN", 1).encode()
        elif kind == "unknown":
            body["private"] = "SYNTHETIC_PRIVATE"
            raw = json.dumps(body).encode()
        elif kind == "bad_utf8":
            raw = b"\xffSYNTHETIC_PRIVATE"
        elif kind == "noncanonical":
            body["expected_command_sequence"] = "00"
            raw = json.dumps(body).encode()
        else:
            target += "?private=SYNTHETIC_PRIVATE"
            raw = json.dumps(body).encode()

        def forbidden(*args, **kwargs):
            raise AssertionError("Runtime dispatched invalid input")

        monkeypatch.setattr(app.state.docx_editor_registry, "command", forbidden)
        response = http.post(
            target,
            content=raw,
            headers={"Content-Type": "application/json", "X-Request-ID": "client-controlled"},
        )
        assert response.status_code == 422, response.text
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert set(data) == {"code", "message", "retryable", "request_id"}
        assert (
            data["request_id"] != "client-controlled" and "SYNTHETIC_PRIVATE" not in response.text
        )


def test_media_body_sizes_and_get_bodies_are_bounded(run_world):
    item = seed(run_world)
    with TestClient(create_app(document_runtime=run_world["runtimes"]["own"])) as http:
        view, _ = opened(http, item)
        target = path(item, view) + "/checkpoint"
        for media in ("text/plain", "application/json; charset=utf-16"):
            assert (
                http.post(target, content="{}", headers={"Content-Type": media}).status_code == 415
            )
        assert (
            http.post(
                target,
                content="{}",
                headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
            ).status_code
            == 415
        )
        assert (
            http.post(
                target, content=b"x" * (65536 + 1), headers={"Content-Type": "application/json"}
            ).status_code
            == 413
        )
        assert http.request("GET", path(item, view), content="SYNTHETIC_PRIVATE").status_code == 422
        assert http.get(path(item, view) + "?unknown=1").status_code == 422
        assert http.get(path(item, view)).json()["command_sequence"] == "0"


def test_large_projection_failure_does_not_hide_metadata_ack_or_undo(run_world):
    item = seed(run_world)
    with TestClient(create_app(document_runtime=run_world["runtimes"]["own"])) as http:
        view, _ = opened(http, item)
        result = http.post(
            path(item, view) + "/commands", json=command(view, "paste_text", "x" * 600000)
        )
        assert result.status_code == 200 and len(result.content) < 65536
        edited = result.json()
        assert http.get(path(item, view) + "/view").status_code == 413
        assert http.get(path(item, view)).json() == edited
        undone = http.post(path(item, view) + "/commands", json=command(edited, "undo")).json()
        assert undone["document"]["is_dirty"] is False
        assert http.get(path(item, view) + "/view").status_code == 200


def test_transport_gate_refuses_concurrent_request_and_releases_after_worker(
    run_world, monkeypatch
):
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"])
    with TestClient(app) as http:
        view, _ = opened(http, item)
        entered, permit = Event(), Event()
        registry = app.state.docx_editor_registry
        real = registry.command

        def blocked(**kwargs):
            entered.set()
            assert permit.wait(5)
            return real(**kwargs)

        monkeypatch.setattr(registry, "command", blocked)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                http.post,
                path(item, view) + "/commands",
                json=command(view, "insert_text", "Once "),
            )
            assert entered.wait(5)
            try:
                busy = http.get(path(item, view))
                assert busy.status_code == 503 and busy.json()["code"] == "editor_busy"
                assert (
                    busy.json()["retryable"] is True and busy.headers["cache-control"] == "no-store"
                )
            finally:
                permit.set()
            assert future.result(10).status_code == 200
        assert http.get(path(item, view)).json()["command_sequence"] == "1"


def test_openapi_new_routes_and_schema_refs_resolve(run_world):
    with TestClient(create_app(document_runtime=run_world["runtimes"]["own"])) as http:
        schema = http.get("/openapi.json").json()
        prefix = "/docx-documents/{document_id}/editor-sessions"
        assert set(schema["paths"][prefix]) == {"post"}
        suffix = prefix + "/{session_id}"
        for tail in ("/commands", "/checkpoint", "/save", "/reconcile", "/close"):
            operation = schema["paths"][suffix + tail]["post"]
            assert operation["requestBody"]["required"] is True
            assert {"200", "404", "409", "410", "413", "415", "422", "500", "503"} <= set(
                operation["responses"]
            )

        def visit(node):
            if isinstance(node, dict):
                if "$ref" in node and node["$ref"].startswith("#/components/schemas/"):
                    assert node["$ref"].rsplit("/", 1)[1] in schema["components"]["schemas"]
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(schema)
