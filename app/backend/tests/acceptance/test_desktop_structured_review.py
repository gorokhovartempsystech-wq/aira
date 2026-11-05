"""Explicit structured fixture composition through actual licensed loopback and owned PG."""

import sys
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_desktop_composition import activate, api, closed, config, license_phase, running
from test_desktop_server import http_for, wait_for
from test_docx_analysis_http import poll, saved_request, started
from test_docx_editor_http import command, opened, path, root

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="native owned macOS composition")


def structured_config(tmp_path):
    return config(tmp_path, analysis_mode="structured_fixture")


def send(http, item, view, action, value=None, *, after=None):
    body = command(view, action, value)
    if after is not None:
        body["command"]["after"] = after
    response = http.post(path(item, view) + "/commands", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def check(http, item, view=None):
    view, body = saved_request(http, item, view)
    receipt = poll(http, started(http, item, body)[0])
    assert receipt["state"]["status"] == "succeeded" and receipt["fixture"]
    response = http.get(root(item) + "/analysis-review")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store", (
        response.text
    )
    review = response.json()
    result = http.get(root(item) + "/analysis-result").json()
    assert result["result"]["schema_version"] == "docx-review/2"
    assert review["view"]["schema_version"] == "docx-review-view/2"
    assert review["view"]["document_context"] == result["result"]["document_context"]
    assert review["view"]["provenance"]["models_version"] == "aira-review-fixture-2"
    assert review["fixture"] and review["view"]["fixture"] and not review["view"]["no_findings"]
    assert "private_provenance" not in result["result"] and "hidden_keys" not in review["view"]
    return view, receipt, review, result


def visibility(http, item, receipt, result, *, revision="0", hidden=True):
    finding = result["result"]["findings"][0]["finding_id"]
    response = http.post(
        root(item) + "/analysis-runs/" + receipt["run_id"] + "/findings/" + finding + "/visibility",
        json=dict(
            command_id=str(uuid4()),
            expected_revision=revision,
            result_sha256=result["stored_result_sha256"],
            hidden=hidden,
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()


def imported(http, raw):
    item = SimpleNamespace(document_id=uuid4())
    response = http.post(
        root(item) + "/import",
        params={"title": "Synthetic structured document"},
        content=raw,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code in (200, 201), response.text
    return item


def test_explicit_modes_keep_legacy_default_and_constructor_inert(tmp_path):
    old = config(tmp_path)
    assert old.analysis_mode == "legacy_fixture"
    new = replace(old, analysis_mode="structured_fixture")
    desktop = api().FixtureDesktop(new)
    assert desktop.view().phase == "new" and not desktop.view().resources_pending
    assert not new.home.exists() and desktop.shutdown(timeout=0)


@pytest.mark.parametrize("mode", [None, True, [], "unknown", "local_model"])
def test_unknown_mode_is_rejected_before_any_home_or_runtime_work(tmp_path, mode):
    with pytest.raises(api().DesktopError) as error:
        config(tmp_path, analysis_mode=mode)
    assert error.value.code == "validation_error"
    assert not (tmp_path / "SYNTHETIC_PRIVATE").exists()


def test_changed_config_mode_is_rechecked_before_opening_home(tmp_path):
    cfg = structured_config(tmp_path)
    object.__setattr__(cfg, "analysis_mode", "unknown")
    desktop = api().FixtureDesktop(cfg)
    try:
        desktop.start()
        wait_for(lambda: desktop.view().phase == "failed")
        assert desktop.view().error_code == "validation_error" and not cfg.home.exists()
    finally:
        closed(desktop)


def test_create_numbered_check_hide_full_restart_retry_unhide_and_exact_export(tmp_path):
    cfg = structured_config(tmp_path)
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        assert http.get("/docx-documents").status_code == 403
        activate(http)
        item = SimpleNamespace(document_id=uuid4())
        response = http.post(root(item) + "/create", params={"title": "Synthetic new requirement"})
        assert response.status_code in (200, 201), response.text
        view, _ = opened(http, item)
        view = send(http, item, view, "insert_text", "First requirement")
        full = http.get(path(item, view) + "/view").json()
        paragraph = full["projection"]["blocks"][0]
        view = send(
            http,
            item,
            view,
            "format",
            [
                dict(
                    anchor=paragraph["anchor"],
                    expected_text="First requirement",
                    list_kind="numbered",
                )
            ],
        )
        view, receipt, review, result = check(http, item, view)
        context = review["view"]["document_context"]
        assert (
            len(context["lists"]) == 1
            and result["result"]["findings"][0]["primary"]["quote"] == "First requirement"
        )
        saved = http.get(root(item) + "/content").content
        visibility(http, item, receipt, result)
        hidden = http.get(root(item) + "/analysis-review").json()
        assert hidden["view"]["no_visible_findings"]
        preferences = http.get(root(item) + "/analysis-preferences").json()
        assert preferences["preferences"]["revision"] == "1"
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        license_phase(http, "active")
        assert http.get(root(item) + "/content").content == saved
        assert http.get(root(item) + "/analysis-review").json() == hidden
        assert http.get(root(item) + "/analysis-preferences").json() == preferences
        retry = http.post(
            root(item) + "/analysis-runs/" + receipt["run_id"] + "/retry",
            json={"client_request_id": str(uuid4())},
        )
        assert retry.status_code == 202, retry.text
        repeated = poll(http, retry.headers["Location"])
        assert repeated["state"]["status"] == "succeeded"
        again = http.get(root(item) + "/analysis-review").json()
        new_result = http.get(root(item) + "/analysis-result").json()
        assert again["view"]["document_context"] == context and again["view"]["no_visible_findings"]
        visibility(http, item, repeated, new_result, revision="1", hidden=False)
        shown = http.get(root(item) + "/analysis-review").json()
        assert shown["view"]["counts"]["visible_findings"] == 1 and not shown["view"]["no_findings"]
        assert http.get(root(item) + "/content").content == saved
    assert [r.operation for r in cfg.transport.requests] == ["activate", "check"]
    assert cfg.transport.requests[0].nonce != cfg.transport.requests[1].nonce


def test_imported_aira_lists_keep_context_under_filters_and_exact_export(tmp_path):
    from test_docx_review_http import preference_body

    from ara.docx_package.creation import NewParagraph, create_docx

    cfg = structured_config(tmp_path)
    raw = create_docx(
        (
            NewParagraph("Heading", "heading1"),
            NewParagraph("First requirement", "numbered"),
            NewParagraph("Second requirement", "bullet"),
        )
    )
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item = imported(http, raw)
        _, _, review, result = check(http, item)
        context = review["view"]["document_context"]
        assert len(context["lists"]) == 2 and context["note_references"] == []
        assert result["result"]["findings"][0]["primary"]["quote"] == "First requirement"
        response = http.post(
            root(item) + "/analysis-preferences",
            json=preference_body(disabled_types=["formulation"]),
        )
        assert response.status_code == 200
        filtered = http.get(root(item) + "/analysis-review").json()["view"]
        assert (
            filtered["document_context"] == context
            and filtered["no_visible_findings"]
            and not filtered["no_findings"]
        )
        assert http.get(root(item) + "/content").content == raw


def test_persisted_hide_survives_distant_edit_but_not_changed_table_context(tmp_path):
    from test_docx_structured_remapping import EVIDENCE, body, cell, numbered, p, row, source, table

    cfg = structured_config(tmp_path)
    center = table(row(cell(p("Cell left")) + cell(numbered(EVIDENCE) + p("Cell right"))))
    raw = source(body(center))[0]
    with running(cfg) as desktop, http_for(desktop.connection()) as http:
        activate(http)
        item = imported(http, raw)
        view, receipt, _, result = check(http, item)
        assert result["result"]["findings"][0]["primary"]["quote"] == EVIDENCE
        visibility(http, item, receipt, result)
        view = send(http, item, view, "insert_text", "Changed distant ")
        view, _, hidden, new_result = check(http, item, view)
        assert hidden["view"]["no_visible_findings"]
        assert new_result["stored_result_sha256"] != result["stored_result_sha256"]
        full = http.get(path(item, view) + "/view").json()
        paragraph = full["projection"]["blocks"][2]["rows"][0]["cells"][0]["blocks"][0]
        value = [
            dict(
                start=dict(anchor=paragraph["spans"][0]["anchor"], offset=0),
                end=dict(anchor=paragraph["spans"][0]["anchor"], offset=len("Cell left")),
                expected_text="Cell left",
                replacement_text="Changed cell",
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
        _, _, visible, _ = check(http, item, view)
        assert (
            visible["view"]["counts"]["visible_findings"] == 1
            and not visible["view"]["no_findings"]
        )
        assert (
            http.get(root(item) + "/analysis-preferences").json()["preferences"]["revision"] == "1"
        )


def test_http_nested_version_metadata_describes_both_supported_public_shapes():
    from ara.docx_analysis_api import _wire as analysis
    from ara.docx_review_api import _wire as review

    for module, operation, key, versions in (
        (
            analysis,
            "result",
            "result",
            ["docx-review/1", "docx-review/2", "docx-review/3", "docx-review/4", "docx-review/5"],
        ),
        (
            review,
            "review",
            "view",
            [
                "docx-review-view/1",
                "docx-review-view/2",
                "docx-review-view/3",
                "docx-review-view/4",
                "docx-review-view/5",
            ],
        ),
    ):
        schema = module.schema(operation)["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["properties"][key]
        assert schema["type"] == "object"
        assert schema["properties"]["schema_version"]["enum"] == versions
        assert "schema_version" in schema["required"] and all(
            v in schema["description"] for v in versions
        )
