"""E3 persistent review presentation through strict optional HTTP routes."""

import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_docx_analysis_http import api_world as api_world
from test_docx_analysis_http import complete, poll, saved_request, started
from test_docx_analysis_supervisor_runtime import wait_for
from test_docx_editor_http import command, path, root
from test_docx_text_edit import seed

from ara.app import create_app
from ara.config import ConfigurationError


def api():
    return importlib.import_module("ara.docx_review_api")


@pytest.fixture
def review_world(api_world):
    api()
    world, item, app, http, supervisor, platform = api_world
    editor, body, location, receipt = complete(api_world)
    raw = http.get(root(item) + "/analysis-result").json()
    return dict(
        world=world,
        item=item,
        app=app,
        http=http,
        s=supervisor,
        p=platform,
        editor=editor,
        body=body,
        run=receipt["run_id"],
        raw=raw,
        finding=raw["result"]["findings"][0]["finding_id"],
    )


def preference_body(*, revision="0", **changes):
    return (
        dict(
            command_id=str(uuid4()),
            expected_revision=revision,
            disabled_types=[],
            show_questions=True,
            show_hidden=False,
        )
        | changes
    )


def visibility(w, *, revision="0", hidden=True, **changes):
    return (
        dict(
            command_id=str(uuid4()),
            expected_revision=revision,
            result_sha256=w["raw"]["stored_result_sha256"],
            hidden=hidden,
        )
        | changes
    )


def visibility_path(w):
    return (
        root(w["item"]) + "/analysis-runs/" + w["run"] + "/findings/" + w["finding"] + "/visibility"
    )


def preferences(w):
    response = w["http"].get(root(w["item"]) + "/analysis-preferences")
    assert response.status_code == 200, response.text
    return response.json()["preferences"]


def review(w):
    response = w["http"].get(root(w["item"]) + "/analysis-review")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_save_analyze_hide_reopen_show_hidden_unhide(review_world):
    w = review_world
    p = preferences(w)
    assert p == dict(
        document_id=str(w["item"].document_id),
        revision="0",
        disabled_types=[],
        show_questions=True,
        show_hidden=False,
    )
    before = review(w)
    assert before["schema_version"] == "docx-review-http/1"
    assert before["fixture"] is True and before["matches_saved_document"] is True
    assert before["view"]["counts"]["visible_findings"] == 1
    response = w["http"].post(visibility_path(w), json=visibility(w))
    assert response.status_code == 200 and response.json()["receipt"]["revision"] == "1"
    hidden = review(w)
    assert hidden["view"]["no_visible_findings"] and not hidden["view"]["no_findings"]
    assert hidden["view"]["counts"]["hidden_findings"] == 1
    assert not hidden["view"]["questions"] and not hidden["view"]["findings"]
    with TestClient(
        create_app(document_runtime=w["world"]["runtimes"]["own"], analysis_supervisor=w["s"])
    ) as reopened:
        assert reopened.get(root(w["item"]) + "/analysis-review").json() == hidden
        response = reopened.post(
            root(w["item"]) + "/analysis-preferences",
            json=preference_body(revision="1", show_hidden=True),
        )
        assert response.status_code == 200 and response.json()["receipt"]["revision"] == "2"
        shown = reopened.get(root(w["item"]) + "/analysis-review").json()["view"]
        assert shown["counts"]["visible_findings"] == 1 and shown["hidden_finding_ids"] == [
            w["finding"]
        ]
        assert (
            reopened.post(
                visibility_path(w), json=visibility(w, revision="2", hidden=False)
            ).status_code
            == 200
        )
    assert review(w)["view"]["counts"]["hidden_findings"] == 0
    assert w["http"].get(root(w["item"]) + "/analysis-result").json() == w["raw"]
    assert w["p"].launches == 1


def test_filters_change_presentation_without_changing_request_or_raw_result(review_world):
    w = review_world
    response = w["http"].post(
        root(w["item"]) + "/analysis-preferences", json=preference_body(show_questions=False)
    )
    assert response.status_code == 200
    data = review(w)["view"]
    assert data["findings"][0]["question"] is None and data["questions"] == []
    response = w["http"].post(
        root(w["item"]) + "/analysis-preferences",
        json=preference_body(revision="1", disabled_types=["formulation"]),
    )
    assert response.status_code == 200
    data = review(w)["view"]
    assert data["counts"]["visible_findings"] == 0 and data["counts"]["total_findings"] == 1
    assert data["no_findings"] is False
    with w["world"]["engine"].connect() as conn:
        request = json.loads(
            bytes(conn.scalar(text("SELECT request_data FROM docx_analysis_attempts")))
        )
    assert (
        request["engine_request"]["disabled_types"] == []
        and request["engine_request"]["dismissed"] == []
    )
    assert w["http"].get(root(w["item"]) + "/analysis-result").json() == w["raw"]


def test_replay_ack_is_old_fact_and_never_reapplies_hidden_state(review_world):
    w = review_world
    first = visibility(w)
    response = w["http"].post(visibility_path(w), json=first)
    assert response.status_code == 200
    ack = response.json()
    assert (
        w["http"]
        .post(visibility_path(w), json=visibility(w, revision="1", hidden=False))
        .status_code
        == 200
    )
    assert w["http"].post(visibility_path(w), json=first).json() == ack
    assert preferences(w)["revision"] == "2" and review(w)["view"]["counts"]["hidden_findings"] == 0
    assert w["http"].post(visibility_path(w), json=first | {"hidden": False}).status_code == 409
    assert (
        w["http"]
        .post(root(w["item"]) + "/analysis-preferences", json=preference_body())
        .status_code
        == 409
    )


@pytest.mark.parametrize(
    "fault,status",
    [
        ("extra", 422),
        ("duplicate", 422),
        ("counter", 422),
        ("boolean", 422),
        ("query", 422),
        ("media", 415),
        ("encoding", 415),
        ("large", 413),
    ],
)
def test_strict_transport_does_not_mutate_preferences(review_world, fault, status):
    w = review_world
    target = root(w["item"]) + "/analysis-preferences"
    body, headers = preference_body(), {"Content-Type": "application/json"}
    if fault == "extra":
        body["private"] = "SYNTHETIC_PRIVATE"
    elif fault == "counter":
        body["expected_revision"] = "00"
    elif fault == "boolean":
        body["show_questions"] = 1
    elif fault == "query":
        target += "?private=SYNTHETIC_PRIVATE"
    elif fault == "media":
        headers["Content-Type"] = "text/plain"
    elif fault == "encoding":
        headers["Content-Encoding"] = "gzip"
    raw = json.dumps(body).encode()
    if fault == "duplicate":
        raw = raw[:-1] + b',"show_hidden":true}'
    elif fault == "large":
        raw = b"x" * 65537
    response = w["http"].post(target, content=raw, headers=headers)
    assert response.status_code == status and response.headers["cache-control"] == "no-store"
    assert "SYNTHETIC_PRIVATE" not in response.text and preferences(w)["revision"] == "0"


def test_get_bodies_foreign_scope_unknown_finding_and_bad_result(review_world):
    w = review_world
    for suffix in (
        "/analysis-preferences",
        "/analysis-review",
        "/analysis-runs/" + w["run"] + "/review",
    ):
        assert w["http"].request("GET", root(w["item"]) + suffix, content="{}").status_code == 422
    other = seed(w["world"], scope="foreign")
    assert w["http"].get(root(other) + "/analysis-preferences").status_code == 404
    assert w["http"].get(root(other) + "/analysis-runs/" + w["run"] + "/review").status_code == 404
    assert (
        w["http"]
        .post(
            visibility_path(w).replace(str(w["item"].document_id), str(other.document_id)),
            json=visibility(w),
        )
        .status_code
        == 404
    )
    assert (
        w["http"]
        .post(visibility_path(w).replace(w["finding"], "df-" + "0" * 64), json=visibility(w))
        .status_code
        == 404
    )
    assert (
        w["http"].post(visibility_path(w), json=visibility(w, result_sha256="0" * 64)).status_code
        == 409
    )
    assert preferences(w)["revision"] == "0"


def test_source_edit_changes_freshness_without_retargeting_old_findings(review_world):
    w = review_world
    before = review(w)
    edited = (
        w["http"]
        .post(
            path(w["item"], w["editor"]) + "/commands",
            json=command(w["editor"], "insert_text", "Changed "),
        )
        .json()
    )
    saved_request(w["http"], w["item"], edited)
    after = review(w)
    assert after["matches_saved_document"] is False
    assert after["current_sha256"] != before["current_sha256"]
    assert after["view"] == before["view"]


def test_preference_change_while_decoding_never_returns_old_filtered_view(
    review_world, monkeypatch
):
    w = review_world
    module = importlib.import_module("ara.docx_review_api._view")
    original = module.present
    entered, release = Event(), Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "present", blocked)
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(w["http"].get, root(w["item"]) + "/analysis-review")
            assert entered.wait(3)
            changed = w["http"].post(
                root(w["item"]) + "/analysis-preferences",
                json=preference_body(disabled_types=["formulation"]),
            )
            assert changed.status_code == 200
            release.set()
            response = future.result()
            assert response.status_code == 409 and response.json()["code"] == "preferences_conflict"
    finally:
        release.set()
    assert review(w)["view"]["counts"]["visible_findings"] == 0


def test_two_view_reads_leave_stop_available(review_world, monkeypatch):
    w = review_world
    w["p"].done.clear()
    location, _ = started(w["http"], w["item"], w["body"] | {"client_request_id": str(uuid4())})
    wait_for(lambda: w["p"].launches == 2)
    active_run = w["http"].get(location).json()["run_id"]
    assert (
        w["http"].get(root(w["item"]) + "/analysis-runs/" + active_run + "/review").status_code
        == 409
    )
    module = importlib.import_module("ara.docx_review_api._view")
    original = module.present
    entered, release = [Event(), Event()], Event()
    entry_lock = Lock()

    def blocked(*args, **kwargs):
        with entry_lock:
            for event in entered:
                if not event.is_set():
                    event.set()
                    break
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "present", blocked)
    try:
        with ThreadPoolExecutor(2) as pool:
            futures = [
                pool.submit(w["http"].get, root(w["item"]) + "/analysis-review") for _ in range(2)
            ]
            assert all(event.wait(3) for event in entered)
            busy = w["http"].get(root(w["item"]) + "/analysis-preferences")
            assert busy.status_code == 503 and busy.json()["code"] == "analysis_busy"
            stopped = w["http"].post(location + "/stop", json={})
            assert stopped.status_code == 202 and stopped.json()["stop_requested"] is True
            release.set()
            assert all(f.result().status_code == 200 for f in futures)
    finally:
        release.set()
        w["p"].done.set()
    assert poll(w["http"], location)["state"]["status"] == "cancelled"


def test_corrupt_result_safe_error_and_installation_schema(review_world):
    w = review_world
    with w["world"]["engine"].begin() as conn:
        conn.execute(
            text("UPDATE docx_analysis_results SET result_data=:data"),
            dict(data=b"SYNTHETIC_PRIVATE"),
        )
    response = w["http"].get(root(w["item"]) + "/analysis-review")
    assert response.status_code == 500 and response.json()["code"] == "storage_error"
    assert "SYNTHETIC_PRIVATE" not in response.text and "findings" not in response.text
    with pytest.raises(ConfigurationError):
        api().install_review(w["app"])
    with pytest.raises(ConfigurationError):
        api().install_review(create_app())
    operation = w["app"].openapi()["paths"]["/docx-documents/{document_id}/analysis-preferences"][
        "post"
    ]
    assert "requestBody" in operation and "200" in operation["responses"]
    assert not any("analysis-preferences" in p for p in create_app().openapi()["paths"])


def test_no_result_is_not_an_empty_success_and_v12_has_no_implicit_upgrade(review_world):
    from test_docx_analysis_storage_migrations import migrate_down

    w = review_world
    empty = seed(w["world"])
    assert w["http"].get(root(empty) + "/analysis-review").status_code == 404
    assert (
        w["http"].get(root(empty) + "/analysis-preferences").json()["preferences"]["revision"]
        == "0"
    )
    migrate_down(w["world"]["engine"], "0012_docx_continuous_timeout")
    response = w["http"].get(root(w["item"]) + "/analysis-preferences")
    assert (
        response.status_code == 503 and response.json()["code"] == "preferences_schema_unavailable"
    )
    assert w["http"].get(root(w["item"]) + "/analysis-result").status_code == 200
    with w["world"]["engine"].connect() as conn:
        assert (
            conn.scalar(text("SELECT version_num FROM alembic_version"))
            == "0012_docx_continuous_timeout"
        )


def test_owner_transfer_during_presentation_blocks_response_without_holding_sql_lock(
    review_world, monkeypatch
):
    w = review_world
    module = importlib.import_module("ara.docx_review_api._view")
    original = module.present

    def transfer(*args, **kwargs):
        result = original(*args, **kwargs)
        with w["world"]["engine"].begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout='500ms'"))
            conn.execute(
                text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
                dict(
                    owner=w["world"]["runtimes"]["foreign"].user_id,
                    project=w["world"]["runtimes"]["own"].project_id,
                ),
            )
        return result

    monkeypatch.setattr(module, "present", transfer)
    response = w["http"].get(root(w["item"]) + "/analysis-review")
    assert response.status_code == 404 and "findings" not in response.text


@pytest.mark.parametrize("fault", ["document", "run", "finding", "hidden", "hash", "command"])
def test_visibility_rejects_noncanonical_locator_and_values(review_world, fault):
    w = review_world
    target, body = visibility_path(w), visibility(w)
    if fault == "document":
        target = target.replace(
            str(w["item"].document_id), str(w["item"].document_id).replace("-", "")
        )
    elif fault == "run":
        target = target.replace(w["run"], w["run"].replace("-", ""))
    elif fault == "finding":
        target = target.replace(w["finding"], "DF-" + "0" * 64)
    elif fault == "hidden":
        body["hidden"] = 1
    elif fault == "hash":
        body["result_sha256"] = "A" * 64
    else:
        body["command_id"] = body["command_id"].replace("-", "")
    response = w["http"].post(target, json=body)
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    assert preferences(w)["revision"] == "0"


def test_latest_review_uses_successful_order_and_pinned_review_stays_available(review_world):
    from hashlib import sha256

    w = review_world
    first = review(w)
    location, _ = started(w["http"], w["item"], w["body"] | {"client_request_id": str(uuid4())})
    next_run = poll(w["http"], location)["run_id"]
    latest = review(w)
    assert latest["run"]["run_id"] == next_run != first["run"]["run_id"]
    pinned = w["http"].get(root(w["item"]) + "/analysis-runs/" + w["run"] + "/review")
    assert pinned.status_code == 200 and pinned.json() == first
    canonical = json.dumps(
        latest["view"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    assert sha256(canonical).hexdigest() == latest["view_sha256"]
