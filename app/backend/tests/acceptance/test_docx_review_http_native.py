"""Native fixture result remains exact while persistent visibility changes through HTTP."""

import importlib
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_docx_analysis_http import build, poll, saved_request, started
from test_docx_analysis_supervisor_runtime import wait_for
from test_docx_editor_http import root
from test_docx_text_edit import seed

from ara.app import create_app


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_analysis_hide_and_new_app_restoration(run_world, tmp_path):
    importlib.import_module("ara.docx_review_api")
    runtime = run_world["runtimes"]["own"]
    s, _ = build(run_world, tmp_path, native=True)
    item = seed(run_world)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        with TestClient(create_app(document_runtime=runtime, analysis_supervisor=s)) as http:
            _, body = saved_request(http, item)
            receipt = poll(http, started(http, item, body)[0])
            assert receipt["state"]["status"] == "succeeded"
            before = http.get(root(item) + "/analysis-review").json()
            assert before["fixture"] and before["view"]["counts"]["visible_findings"] == 1
            finding = before["view"]["findings"][0]["finding_id"]
            response = http.post(
                root(item)
                + "/analysis-runs/"
                + receipt["run_id"]
                + "/findings/"
                + finding
                + "/visibility",
                json=dict(
                    command_id=str(uuid4()),
                    expected_revision="0",
                    result_sha256=before["view"]["stored_result_sha256"],
                    hidden=True,
                ),
            )
            assert response.status_code == 200
            hidden = http.get(root(item) + "/analysis-review").json()
            assert hidden["view"]["no_visible_findings"] and hidden["view"]["fixture"]
            assert hidden["view"]["no_findings"] is False
        with TestClient(create_app(document_runtime=runtime, analysis_supervisor=s)) as fresh:
            assert fresh.get(root(item) + "/analysis-review").json() == hidden
            assert (
                fresh.get(root(item) + "/analysis-preferences").json()["preferences"]["revision"]
                == "1"
            )
    finally:
        assert s.shutdown(timeout=5)
