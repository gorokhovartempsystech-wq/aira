"""E4C2 effective visibility through the same explicit local analysis API."""

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_docx_analysis_http import api_world as api_world
from test_docx_analysis_http import poll, saved_request, started
from test_docx_editor_http import command, path, root
from test_docx_review_http import preference_body
from test_docx_review_remapping import records
from test_docx_text_edit import seed

from ara.app import create_app
from ara.docx_review_preferences import set_hidden as exact_hide
from ara.docx_review_resolution import ResolutionLimits


@pytest.fixture
def effective_world(api_world):
    world, _, app, http, supervisor, platform = api_world
    item = seed(world, records()[0].source_data)
    view, body = saved_request(http, item)
    receipt = poll(http, started(http, item, body)[0])
    assert receipt["state"]["status"] == "succeeded"
    raw = http.get(root(item) + "/analysis-result").json()
    return dict(
        world=world, item=item, app=app, http=http, s=supervisor, p=platform, editor=view, raw=raw
    )


def prefs(w):
    response = w["http"].get(root(w["item"]) + "/analysis-preferences")
    assert response.status_code == 200
    return response.json()["preferences"]


def review(w):
    response = w["http"].get(root(w["item"]) + "/analysis-review")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def visibility(w, raw=None, hidden=True):
    raw = raw or w["raw"]
    finding = raw["result"]["findings"][0]["finding_id"]
    target = (
        root(w["item"])
        + "/analysis-runs/"
        + raw["run"]["run_id"]
        + "/findings/"
        + finding
        + "/visibility"
    )
    body = dict(
        command_id=str(uuid4()),
        expected_revision=prefs(w)["revision"],
        result_sha256=raw["stored_result_sha256"],
        hidden=hidden,
    )
    return target, body


def change_and_check(w, *, block=-1):
    full = w["http"].get(path(w["item"], w["editor"]) + "/view").json()
    paragraph = full["projection"]["blocks"][block]
    caret = dict(anchor=paragraph["anchor"], offset=len(paragraph["text"]), affinity="right")
    response = w["http"].post(
        path(w["item"], w["editor"]) + "/commands",
        json=command(w["editor"], "capture", dict(anchor=caret, focus=caret)),
    )
    assert response.status_code == 200, response.text
    view = response.json()
    response = w["http"].post(
        path(w["item"], view) + "/commands", json=command(view, "insert_text", " changed")
    )
    assert response.status_code == 200, response.text
    w["editor"], body = saved_request(w["http"], w["item"], response.json())
    receipt = poll(w["http"], started(w["http"], w["item"], body)[0])
    assert receipt["state"]["status"] == "succeeded"
    return w["http"].get(root(w["item"]) + "/analysis-result").json()


def clear_body(w):
    return dict(command_id=str(uuid4()), expected_revision=prefs(w)["revision"])


def clear_path(w):
    return root(w["item"]) + "/analysis-preferences/clear-hidden"


def test_http_far_edit_keeps_hide_then_unhide_and_reopen(effective_world):
    w = effective_world
    target, body = visibility(w)
    assert w["http"].post(target, json=body).status_code == 200
    assert review(w)["view"]["no_visible_findings"]
    raw = change_and_check(w)
    hidden = review(w)
    assert (
        hidden["view"]["no_visible_findings"] and hidden["view"]["counts"]["hidden_findings"] == 1
    )
    assert hidden["fixture"] and not hidden["view"]["no_findings"]
    target, body = visibility(w, raw)
    response = w["http"].post(target, json=body)
    assert response.status_code == 200 and response.json()["receipt"]["changed"] is False
    with w["world"]["engine"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_review_dismissals")) == 1
    with TestClient(
        create_app(document_runtime=w["world"]["runtimes"]["own"], analysis_supervisor=w["s"])
    ) as reopened:
        assert reopened.get(root(w["item"]) + "/analysis-review").json()["view"][
            "no_visible_findings"
        ]
        target, body = visibility(w, raw, False)
        response = reopened.post(target, json=body)
        assert response.status_code == 200 and response.json()["receipt"]["changed"] is True
    assert review(w)["view"]["counts"]["visible_findings"] == 1 and w["p"].launches == 2
    assert w["http"].get(root(w["item"]) + "/analysis-result").json() == raw


def test_changed_primary_paragraph_is_visible_despite_old_hide(effective_world):
    w = effective_world
    target, body = visibility(w)
    assert w["http"].post(target, json=body).status_code == 200
    change_and_check(w, block=0)
    result = review(w)
    assert (
        result["view"]["counts"]["visible_findings"] == 1
        and result["view"]["counts"]["hidden_findings"] == 0
    )


def test_http_unhide_removes_all_legacy_origins_for_current_finding(effective_world):
    w = effective_world
    target, body = visibility(w)
    assert w["http"].post(target, json=body).status_code == 200
    second = change_and_check(w)
    exact_hide(
        w["world"]["runtimes"]["own"],
        document_id=w["item"].document_id,
        command_id=uuid4(),
        expected_revision=1,
        run_id=UUID(second["run"]["run_id"]),
        result_sha256=second["stored_result_sha256"],
        finding_id=second["result"]["findings"][0]["finding_id"],
        hidden=True,
    )
    third = change_and_check(w)
    assert review(w)["view"]["no_visible_findings"]
    target, body = visibility(w, third, False)
    response = w["http"].post(target, json=body)
    assert response.status_code == 200 and response.json()["receipt"]["changed"]
    assert review(w)["view"]["counts"]["hidden_findings"] == 0
    with w["world"]["engine"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM docx_review_dismissals")) == 0


def test_explicit_clear_preserves_filters_raw_result_and_original_ack(effective_world):
    w = effective_world
    target, body = visibility(w)
    hidden_ack = w["http"].post(target, json=body)
    assert hidden_ack.status_code == 200
    response = w["http"].post(
        root(w["item"]) + "/analysis-preferences",
        json=preference_body(revision="1", show_questions=False, disabled_types=["formulation"]),
    )
    assert response.status_code == 200
    clear = clear_body(w)
    response = w["http"].post(clear_path(w), json=clear)
    assert response.status_code == 200 and response.json()["receipt"]["changed"]
    assert response.json()["receipt"]["kind"] == "unhide"
    assert w["http"].post(clear_path(w), json=clear).json() == response.json()
    assert w["http"].post(target, json=body).json() == hidden_ack.json()
    result = review(w)
    assert result["preferences"]["revision"] == "3" and result["preferences"]["disabled_types"] == [
        "formulation"
    ]
    assert (
        not result["preferences"]["show_questions"]
        and result["view"]["counts"]["hidden_findings"] == 0
    )
    assert result["view"]["counts"]["visible_findings"] == 0 and not result["view"]["no_findings"]
    assert (
        w["http"].get(root(w["item"]) + "/analysis-result").json() == w["raw"]
        and w["p"].launches == 1
    )


def test_resolution_limit_can_be_cleared_explicitly_without_changing_result(
    effective_world, monkeypatch
):
    w = effective_world
    target, body = visibility(w)
    assert w["http"].post(target, json=body).status_code == 200
    raw = change_and_check(w)
    module = importlib.import_module("ara.docx_review_api._view")
    original = module.load_inputs

    def small(session, state, target):
        return original(session, state, target, limits=ResolutionLimits(max_origins=1))

    monkeypatch.setattr(module, "load_inputs", small)
    response = w["http"].get(root(w["item"]) + "/analysis-review")
    assert response.status_code == 413 and response.json()["code"] == "preferences_resolution_limit"
    assert prefs(w)["revision"] == "1"
    cleared = w["http"].post(clear_path(w), json=clear_body(w))
    assert cleared.status_code == 200
    assert review(w)["view"]["counts"]["visible_findings"] == 1
    assert w["http"].get(root(w["item"]) + "/analysis-result").json() == raw


@pytest.mark.parametrize(
    "fault,status",
    [
        ("extra", 422),
        ("duplicate", 422),
        ("counter", 422),
        ("uuid", 422),
        ("query", 422),
        ("media", 415),
        ("large", 413),
    ],
)
def test_clear_has_strict_transport_and_no_side_effect_on_rejection(effective_world, fault, status):
    w = effective_world
    target, body = clear_path(w), clear_body(w)
    headers = {"Content-Type": "application/json"}
    if fault == "extra":
        body["hidden"] = True
    elif fault == "counter":
        body["expected_revision"] = 0
    elif fault == "uuid":
        body["command_id"] = body["command_id"].replace("-", "")
    elif fault == "query":
        target += "?private=SYNTHETIC_PRIVATE"
    elif fault == "media":
        headers["Content-Type"] = "text/plain"
    raw = json.dumps(body).encode()
    if fault == "duplicate":
        raw = raw[:-1] + b',"expected_revision":"0"}'
    elif fault == "large":
        raw = b"x" * 65537
    response = w["http"].post(target, content=raw, headers=headers)
    assert response.status_code == status and response.headers["cache-control"] == "no-store"
    assert prefs(w)["revision"] == "0" and "SYNTHETIC_PRIVATE" not in response.text


def test_clear_scope_openapi_and_default_app_boundary(effective_world):
    w = effective_world
    foreign = seed(w["world"], scope="foreign")
    response = w["http"].post(
        root(foreign) + "/analysis-preferences/clear-hidden", json=clear_body(w)
    )
    assert response.status_code == 404
    spec = w["app"].openapi()["paths"][
        "/docx-documents/{document_id}/analysis-preferences/clear-hidden"
    ]["post"]
    fields = spec["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert set(fields) == {"command_id", "expected_revision"} and "200" in spec["responses"]
    assert not any("clear-hidden" in path for path in create_app().openapi()["paths"])


def test_clear_requires_v13_without_migration(effective_world):
    w = effective_world
    body = clear_body(w)
    with w["world"]["engine"].begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num='0012_docx_continuous_timeout'"))
    try:
        response = w["http"].post(clear_path(w), json=body)
        assert response.status_code == 503
        assert response.json()["code"] == "preferences_schema_unavailable"
        with w["world"]["engine"].connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM docx_review_preferences")) == 0
            assert (
                conn.scalar(text("SELECT version_num FROM alembic_version"))
                == "0012_docx_continuous_timeout"
            )
    finally:
        with w["world"]["engine"].begin() as conn:
            conn.execute(
                text("UPDATE alembic_version SET version_num='0013_docx_review_preferences'")
            )


def test_clear_does_not_mask_corrupt_current_result(effective_world):
    w = effective_world
    target, body = visibility(w)
    assert w["http"].post(target, json=body).status_code == 200
    clear = clear_body(w)
    with w["world"]["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_analysis_results SET result_data=:data"),
            dict(data=b"SYNTHETIC_PRIVATE"),
        )
    response = w["http"].post(clear_path(w), json=clear)
    assert response.status_code == 200 and response.json()["receipt"]["changed"]
    for suffix in ("/analysis-review", "/analysis-result"):
        response = w["http"].get(root(w["item"]) + suffix)
        assert response.status_code == 500
        assert "SYNTHETIC_PRIVATE" not in response.text and "findings" not in response.text
    assert prefs(w)["revision"] == "2"


def test_clear_obeys_same_ordinary_admission_limit(effective_world, monkeypatch):
    w = effective_world
    body = clear_body(w)
    module = importlib.import_module("ara.docx_review_api._view")
    original = module.resolve
    entered, release, lock = [Event(), Event()], Event(), Lock()

    def blocked(inputs):
        with lock:
            for event in entered:
                if not event.is_set():
                    event.set()
                    break
        assert release.wait(10)
        return original(inputs)

    monkeypatch.setattr(module, "resolve", blocked)
    try:
        with ThreadPoolExecutor(2) as pool:
            try:
                pending = [
                    pool.submit(w["http"].get, root(w["item"]) + "/analysis-review")
                    for _ in range(2)
                ]
                assert all(event.wait(3) for event in entered)
                response = w["http"].post(clear_path(w), json=body)
                assert response.status_code == 503 and response.json()["code"] == "analysis_busy"
            finally:
                release.set()
            assert all(future.result().status_code == 200 for future in pending)
    finally:
        release.set()
    assert prefs(w)["revision"] == "0"
