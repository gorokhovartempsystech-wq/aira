"""Expiry while a confirmed fixture run is still pending, including user Stop."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_desktop_access_editor import activate, components
from test_docx_analysis_http import build, poll, saved_request, started
from test_docx_analysis_supervisor_runtime import wait_for
from test_docx_editor_http import root
from test_docx_text_edit import seed

from ara.app import create_app


@pytest.mark.parametrize("stop", [False, True])
def test_pending_run_crosses_license_expiry_without_loss_or_new_admission(
    run_world, tmp_path, stop
):
    worker_root = tmp_path / "worker"
    worker_root.mkdir(mode=0o700)
    supervisor, platform = build(run_world, worker_root)
    platform.done.clear()
    item = seed(run_world)
    app = create_app(document_runtime=run_world["runtimes"]["own"], analysis_supervisor=supervisor)
    client, clock, http = components(tmp_path, app)
    supervisor.start()
    wait_for(lambda: supervisor.view().phase == "ready")
    try:
        with http:
            activate(http, client)
            _, body = saved_request(http, item)
            location, _ = started(http, item, body)
            assert platform.entered.wait(5)
            assert http.get(location).json()["phase"] != "finished"
            clock.value = client.require_active().deadline_ns
            assert (
                http.post(
                    root(item) + "/analysis-runs", json={**body, "client_request_id": str(uuid4())}
                ).status_code
                == 403
            )
            if stop:
                assert http.post(location + "/stop", json={}).status_code == 202
                assert platform.stopped.wait(5)
            platform.done.set()
            receipt = poll(http, location)
            assert receipt["state"]["status"] == ("cancelled" if stop else "succeeded")
            if not stop:
                result = http.get(root(item) + "/analysis-result")
                assert result.status_code == 200 and result.json()["fixture"] is True
            with run_world["engine"].connect() as connection:
                assert connection.scalar(text("SELECT count(*) FROM docx_analysis_runs")) == 1
    finally:
        client.close()
        platform.done.set()
        platform.cleaned.set()
        platform.launch_gate.set()
        assert supervisor.shutdown(timeout=5)
