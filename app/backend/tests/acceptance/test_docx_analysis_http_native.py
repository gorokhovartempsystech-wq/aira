"""D native editor→save→analysis→verified HTTP result; no model claim."""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient
from test_docx_analysis_http import build, poll, saved_request, started
from test_docx_analysis_supervisor_runtime import wait_for
from test_docx_editor_http import command, path, root
from test_docx_text_edit import seed

from ara.app import create_app


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_editor_save_check_edit_check_and_reopen(run_world, tmp_path):
    importlib.import_module("ara.docx_analysis_api")
    s, _ = build(run_world, tmp_path, native=True)
    runtime = run_world["runtimes"]["own"]
    item = seed(run_world)
    app = create_app(document_runtime=runtime, analysis_supervisor=s)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        with TestClient(app) as http:
            view, body = saved_request(http, item)
            first = poll(http, started(http, item, body)[0])
            assert first["state"]["status"] == "succeeded"
            edited = http.post(
                path(item, view) + "/commands", json=command(view, "insert_text", "New ")
            ).json()
            _, body = saved_request(http, item, edited)
            location, _ = started(http, item, body)
            second = poll(http, location)
            assert second["state"]["status"] == "succeeded" and second["run_id"] != first["run_id"]
            result = http.get(root(item) + "/analysis-result").json()
            assert result["result"]["findings"][0]["primary"]["quote"] == "New Device 🧪"
            assert result["matches_saved_document"] and result["fixture"]
        with TestClient(create_app(document_runtime=runtime, analysis_supervisor=s)) as reopened:
            assert reopened.get(root(item) + "/analysis-result").json() == result
            assert poll(reopened, started(reopened, item, body)[0])["run_id"] == second["run_id"]
    finally:
        assert s.shutdown(timeout=5)
