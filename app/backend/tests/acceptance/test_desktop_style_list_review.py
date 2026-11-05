"""Explicit style-list fixture uses owned desktop resources and persists the full review."""

import sys
from dataclasses import replace
from uuid import uuid4

import pytest
from test_desktop_composition import activate, api, config, license_phase, running
from test_desktop_server import http_for
from test_desktop_structured_review import imported, send, visibility
from test_docx_analysis_http import poll, saved_request, started
from test_docx_editor_http import path, root
from test_docx_style_list_integration import fixture

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned macOS composition")


def style_list_config(tmp_path):
    return config(tmp_path, analysis_mode="style_lists_fixture")


def check(http, item, view=None):
    view, body = saved_request(http, item, view)
    receipt = poll(http, started(http, item, body)[0])
    assert receipt["state"]["status"] == "succeeded" and receipt["fixture"]
    response = http.get(root(item) + "/analysis-review")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    review = response.json()
    result = http.get(root(item) + "/analysis-result").json()
    assert result["result"]["schema_version"] == "docx-review/4"
    assert review["view"]["schema_version"] == "docx-review-view/4"
    assert review["view"]["document_context"] == result["result"]["document_context"]
    assert review["fixture"] and review["view"]["fixture"] and not review["view"]["no_findings"]
    assert "private_provenance" not in result["result"] and "hidden_keys" not in review["view"]
    return view, receipt, review, result


def test_style_list_mode_is_explicit_with_legacy_constructor_unchanged(tmp_path):
    old = config(tmp_path)
    assert old.analysis_mode == "legacy_fixture"
    cfg = replace(old, analysis_mode="style_lists_fixture")
    desktop = api().FixtureDesktop(cfg)
    assert desktop.view().phase == "new" and not cfg.home.exists()
    assert desktop.shutdown(timeout=0)


def test_style_list_import_check_hide_full_restart_retry_unhide_and_exact_export(tmp_path):
    cfg = style_list_config(tmp_path)
    raw = fixture()[0]
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        assert http.get("/docx-documents").status_code == 403
        activate(http)
        item = imported(http, raw)
        _, receipt, review, result = check(http, item)
        context = review["view"]["document_context"]
        assert [x["label"] for x in context["lists"]] == ["IV.", "IV.i"]
        assert result["result"]["findings"][0]["primary"]["quote"] == "abcd"
        visibility(http, item, receipt, result)
        hidden = http.get(root(item) + "/analysis-review").json()
        preferences = http.get(root(item) + "/analysis-preferences").json()
        assert (
            hidden["view"]["no_visible_findings"] and preferences["preferences"]["revision"] == "1"
        )
        assert http.get(root(item) + "/content").content == raw
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
        shown = http.get(root(item) + "/analysis-review").json()
        assert shown["view"]["counts"]["visible_findings"] == 1 and not shown["view"]["no_findings"]
        assert http.get(root(item) + "/content").content == raw
    assert [r.operation for r in cfg.transport.requests] == ["activate", "check"]
    assert cfg.transport.requests[0].nonce != cfg.transport.requests[1].nonce


def test_style_list_hide_survives_distant_edit_but_changed_literal_returns(tmp_path):
    cfg = style_list_config(tmp_path)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item = imported(http, fixture()[0])
        view, receipt, _, result = check(http, item)
        visibility(http, item, receipt, result)
        view = send(http, item, view, "insert_text", "Changed distant ")
        view, _, hidden, _ = check(http, item, view)
        assert hidden["view"]["no_visible_findings"]
        full = http.get(path(item, view) + "/view").json()
        paragraph = full["projection"]["blocks"][3]
        span = paragraph["spans"][0]
        value = [
            dict(
                start=dict(anchor=span["anchor"], offset=0),
                end=dict(anchor=span["anchor"], offset=2),
                expected_text="ab",
                replacement_text="XY",
            )
        ]
        view = send(
            http,
            item,
            view,
            "range_edit",
            value,
            after=dict(anchor=dict(block_index=0, offset=0), focus=dict(block_index=0, offset=0)),
        )
        _, _, visible, result = check(http, item, view)
        assert visible["view"]["counts"]["visible_findings"] == 1
        assert result["result"]["findings"][0]["primary"]["quote"] == "XYcd"
        assert (
            http.get(root(item) + "/analysis-preferences").json()["preferences"]["revision"] == "1"
        )
