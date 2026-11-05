"""Independent ordinary files through licensed HTTP, owned restart and exact export."""

import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from test_desktop_composition import activate, api, config, license_phase, running
from test_desktop_server import http_for
from test_desktop_structured_review import imported, send, visibility
from test_docx_analysis_http import poll, saved_request, started
from test_docx_editor_http import root
from test_docx_visible_word import CASES, PROFILE, parts, source

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned macOS composition")


def word_config(tmp_path):
    return config(tmp_path, analysis_mode="word_fixture")


def check(http, item, view=None):
    view, body = saved_request(http, item, view)
    receipt = poll(http, started(http, item, body)[0])
    assert receipt["state"]["status"] == "succeeded" and receipt["fixture"]
    response = http.get(root(item) + "/analysis-review")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    review = response.json()
    result = http.get(root(item) + "/analysis-result").json()
    assert (
        result["result"]["schema_version"] == "docx-review/5"
        and result["result"]["profile"] == PROFILE
    )
    assert review["view"]["schema_version"] == "docx-review-view/5"
    assert review["view"]["document_context"] == result["result"]["document_context"]
    assert review["fixture"] and review["view"]["fixture"] and not review["view"]["no_findings"]
    assert "private_provenance" not in result["result"] and "hidden_keys" not in review["view"]
    return view, receipt, review, result


def test_word_mode_is_explicit_and_constructor_inert(tmp_path):
    old = config(tmp_path)
    assert old.analysis_mode == "legacy_fixture"
    cfg = replace(old, analysis_mode="word_fixture")
    desktop = api().FixtureDesktop(cfg)
    assert desktop.view().phase == "new" and not cfg.home.exists()
    assert desktop.shutdown(timeout=0)


def test_six_ordinary_documents_import_check_and_export_all_original_bytes(tmp_path):
    cfg = word_config(tmp_path)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        assert http.get("/docx-documents").status_code == 403
        activate(http)
        for case in CASES:
            raw = source(case)
            item = imported(http, raw)
            _, _, review, result = check(http, item)
            context = review["view"]["document_context"]
            assert bool(context["lists"]) == (case in ("bullet", "numbered"))
            assert result["result"]["findings"][0]["primary"]["quote"]
            assert http.get(root(item) + "/content").content == raw


def test_word_hide_close_fresh_license_retry_show_and_exact_export(tmp_path):
    cfg = word_config(tmp_path)
    raw = source("numbered")
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item = imported(http, raw)
        _, receipt, review, result = check(http, item)
        context = review["view"]["document_context"]
        assert [x["label"] for x in context["lists"]] == ["1.", "2."]
        visibility(http, item, receipt, result)
        hidden = http.get(root(item) + "/analysis-review").json()
        preferences = http.get(root(item) + "/analysis-preferences").json()
        assert (
            hidden["view"]["no_visible_findings"] and preferences["preferences"]["revision"] == "1"
        )
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        license_phase(http, "active")
        assert http.get(root(item) + "/analysis-review").json() == hidden
        assert http.get(root(item) + "/analysis-preferences").json() == preferences
        retry = http.post(
            root(item) + "/analysis-runs/" + receipt["run_id"] + "/retry",
            json={"client_request_id": str(uuid4())},
        )
        assert retry.status_code == 202
        repeated = poll(http, retry.headers["Location"])
        assert repeated["state"]["status"] == "succeeded"
        again = http.get(root(item) + "/analysis-review").json()
        new_result = http.get(root(item) + "/analysis-result").json()
        assert again["view"]["document_context"] == context and again["view"]["no_visible_findings"]
        visibility(http, item, repeated, new_result, revision="1", hidden=False)
        assert (
            http.get(root(item) + "/analysis-review").json()["view"]["counts"]["visible_findings"]
            == 1
        )
        assert http.get(root(item) + "/content").content == raw
    assert [r.operation for r in cfg.transport.requests] == ["activate", "check"]
    assert cfg.transport.requests[0].nonce != cfg.transport.requests[1].nonce


@pytest.mark.parametrize("case", ("plain", "numbered"))
def test_manual_edit_saved_check_and_export_preserve_auxiliary_parts(tmp_path, case):
    cfg = word_config(tmp_path)
    raw = source(case)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item = imported(http, raw)
        view, receipt, _, result = check(http, item)
        visibility(http, item, receipt, result)
        view = send(http, item, view, "insert_text", "Новое ")
        _, _, current, result = check(http, item, view)
        assert current["view"]["counts"]["visible_findings"] == 1
        assert result["result"]["findings"][0]["primary"]["quote"].startswith("Новое ")
        saved = http.get(root(item) + "/content").content
        before, after = parts(raw), parts(saved)
        assert (
            before.keys() == after.keys()
            and before["word/document.xml"] != after["word/document.xml"]
        )
        assert all(after[k] == v for k, v in before.items() if k != "word/document.xml")
