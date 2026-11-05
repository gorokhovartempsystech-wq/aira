"""The real native fixture child and editor preserve conservative hidden decisions."""

import sys

import pytest
from fastapi.testclient import TestClient
from test_docx_analysis_http import build, poll, saved_request, started
from test_docx_analysis_supervisor_runtime import wait_for
from test_docx_editor_http import root
from test_docx_review_effective_http import (
    change_and_check,
    clear_body,
    clear_path,
    review,
    visibility,
)
from test_docx_review_http import preference_body
from test_docx_review_remapping import records
from test_docx_text_edit import seed

from ara.app import create_app


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_edit_recheck_effective_visibility_clear_and_reopen(run_world, tmp_path):
    runtime = run_world["runtimes"]["own"]
    s, _ = build(run_world, tmp_path, native=True)
    item = seed(run_world, records()[0].source_data)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        with TestClient(create_app(document_runtime=runtime, analysis_supervisor=s)) as http:
            editor, body = saved_request(http, item)
            receipt = poll(http, started(http, item, body)[0])
            assert receipt["state"]["status"] == "succeeded"
            raw = http.get(root(item) + "/analysis-result").json()
            w = dict(world=run_world, item=item, http=http, editor=editor, raw=raw)
            target, body = visibility(w)
            ack = http.post(target, json=body)
            assert ack.status_code == 200 and review(w)["view"]["no_visible_findings"]
            current = change_and_check(w)
            hidden = review(w)
            assert hidden["fixture"] and hidden["view"]["counts"]["hidden_findings"] == 1
            assert hidden["matches_saved_document"] and not hidden["view"]["no_findings"]
            assert current["run"]["source_sha256"] != raw["run"]["source_sha256"]
            response = http.post(
                root(item) + "/analysis-preferences",
                json=preference_body(revision="1", show_hidden=True),
            )
            assert response.status_code == 200
            shown = review(w)["view"]
            assert (
                shown["counts"]["visible_findings"] == 1 and len(shown["hidden_finding_ids"]) == 1
            )
            response = http.post(clear_path(w), json=clear_body(w))
            assert response.status_code == 200 and response.json()["receipt"]["changed"]
            assert http.post(target, json=body).json() == ack.json()
            final = review(w)
            assert final["view"]["counts"]["hidden_findings"] == 0
            assert http.get(root(item) + "/analysis-result").json() == current
        with TestClient(create_app(document_runtime=runtime, analysis_supervisor=s)) as fresh:
            assert fresh.get(root(item) + "/analysis-review").json() == final
            assert final["preferences"]["revision"] == "3"
    finally:
        assert s.shutdown(timeout=5)
