"""Real editor and analysis API behind licensing, in disposable PostgreSQL only."""

import secrets
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from test_desktop_access import LOCAL, api
from test_docx_analysis_http import build, poll, saved_request, started
from test_docx_analysis_supervisor_runtime import wait_for
from test_docx_editor_downloads import working
from test_docx_editor_http import command, control, opened, path, root
from test_docx_text_edit import seed
from test_licensing_client_runtime import Clock, Transport, done
from test_licensing_client_transport import ORIGIN
from test_licensing_policy import DEVICE, synthetic_key

from ara.app import create_app
from ara.docx_documents import get_docx
from ara.licensing.client import ActivationStore, LicenseClient


def components(tmp_path, inner):
    clock, transport, token = Clock(), Transport(), secrets.token_bytes(32)
    client = LicenseClient(
        ORIGIN,
        ActivationStore(tmp_path / "license"),
        clock=clock,
        transport=transport,
        device_provider=lambda: DEVICE,
    )
    wrapper = api().LicensedApplication(inner, client, origin=LOCAL, session_token=token)
    http = TestClient(
        wrapper,
        base_url=LOCAL,
        client=("127.0.0.1", 50123),
        headers={"X-AIRA-Session": token.hex()},
    )
    return client, clock, http


def activate(http, client):
    result = http.post("/desktop/license/activate", json={"license_key": synthetic_key()})
    assert result.status_code == 202
    assert done(client).phase == "active"
    assert http.get("/desktop/license").json()["preservation_available"]


def test_editor_expiry_preserves_checkpoint_save_exact_working_and_saved_docx(run_world, tmp_path):
    runtime = run_world["runtimes"]["own"]
    item = seed(run_world)
    inner = create_app(document_runtime=runtime)
    client, clock, http = components(tmp_path, inner)
    before = get_docx(runtime, document_id=item.document_id)
    try:
        with http:
            assert http.get(root(item) + "/content").status_code == 403
            activate(http, client)
            new_id = uuid4()
            assert (
                http.post(
                    f"/docx-documents/{new_id}/create", params={"title": "Synthetic"}
                ).status_code
                == 200
            )
            view, _ = opened(http, item)
            edited_response = http.post(
                path(item, view) + "/commands",
                json=command(view, "insert_text", "Saved after expiry "),
            )
            assert edited_response.status_code == 200
            edited = edited_response.json()
            expected = inner.state.docx_editor_registry.snapshot(
                document_id=item.document_id, session_id=UUID(view["session_id"])
            ).editor.document.data
            clock.value = client.require_active().deadline_ns
            denied = http.post(
                path(item, view) + "/commands",
                json=command(edited, "insert_text", "Must not appear "),
            )
            assert denied.status_code == 403
            assert http.post(root(item) + "/analysis-runs", json={}).status_code == 403
            assert (
                http.post(
                    f"/docx-documents/{uuid4()}/create", params={"title": "Denied"}
                ).status_code
                == 403
            )
            assert get_docx(runtime, document_id=item.document_id) == before
            rescue = http.post(path(item, view) + "/working-content", json=working(edited))
            assert rescue.status_code == 200 and rescue.content == expected
            checkpoint = http.post(path(item, view) + "/checkpoint", json=control(edited))
            assert checkpoint.status_code == 200
            edited = checkpoint.json()
            save_body = control(edited)
            saved_response = http.post(path(item, view) + "/save", json=save_body)
            assert saved_response.status_code == 200
            saved = saved_response.json()
            assert saved["document"]["is_dirty"] is False
            target = {
                **save_body,
                "expected_command_sequence": saved["command_sequence"],
                "expected_session_revision": saved["document"]["session_revision"],
            }
            saved_copy = http.post(path(item, view) + "/saved-content", json=target)
            assert saved_copy.status_code == 200 and saved_copy.content == expected
            assert http.get(root(item) + "/content").content == expected
            assert http.post(path(item, view) + "/close", json=control(saved)).status_code == 200
            assert http.post(root(item) + "/editor-sessions", json={}).status_code == 403
            assert http.get("/documents").status_code == 404
    finally:
        client.close()
    current = get_docx(runtime, document_id=item.document_id)
    assert current.current_data == expected and current.original_data == before.original_data
    assert current.storage_revision == before.storage_revision + 1


def test_accepted_fixture_analysis_result_survives_expiry_but_new_run_retry_do_not(
    run_world, tmp_path
):
    (tmp_path / "worker").mkdir(mode=0o700)
    supervisor, platform = build(run_world, tmp_path / "worker")
    item = seed(run_world)
    inner = create_app(
        document_runtime=run_world["runtimes"]["own"], analysis_supervisor=supervisor
    )
    client, clock, http = components(tmp_path, inner)
    supervisor.start()
    wait_for(lambda: supervisor.view().phase == "ready")
    try:
        with http:
            activate(http, client)
            _, body = saved_request(http, item)
            location, _ = started(http, item, body)
            clock.value = client.require_active().deadline_ns
            receipt = poll(http, location)
            assert receipt["state"]["status"] == "succeeded"
            result = http.get(root(item) + "/analysis-result")
            assert result.status_code == 200 and result.json()["fixture"] is True
            run_id = receipt["run_id"]
            assert (
                http.post(
                    root(item) + f"/analysis-runs/{run_id}/retry",
                    json={"client_request_id": str(uuid4())},
                ).status_code
                == 403
            )
            assert (
                http.post(
                    root(item) + "/analysis-runs", json={**body, "client_request_id": str(uuid4())}
                ).status_code
                == 403
            )
            assert http.post(location + "/stop", json={}).status_code == 202
            assert http.get(root(item) + "/analysis-review").status_code == 200
    finally:
        client.close()
        platform.done.set()
        platform.cleaned.set()
        platform.launch_gate.set()
        assert supervisor.shutdown(timeout=5)
