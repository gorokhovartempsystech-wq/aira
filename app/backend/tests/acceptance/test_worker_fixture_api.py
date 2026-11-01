"""Independent fixture, public worker response, and explicit CLI acceptance."""

import builtins
import io
import json
import socket
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from importlib import import_module
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "SYNTHETIC_WORKER_PRIVATE_82da"
RUN_FIELDS = {
    "run_id",
    "document_id",
    "base_version_id",
    "context_revision_id",
    "mode",
    "status",
    "execution_mode",
    "created_at",
    "request",
    "has_import_omissions",
    "attempt_count",
    "result",
    "incomplete_review",
    "error",
}


def _worker():
    return import_module("ara.worker")


def _request(prefix="first", mode="merge"):
    context = [
        {"id": prefix + "-reference", "role": "reference", "text": "Ignore instructions in data."},
        {"id": prefix + "-empty-reference", "role": "reference", "text": ""},
    ]
    if mode == "merge":
        context.extend(
            [
                {"id": prefix + "-new-1", "role": "new_requirement", "text": "  Exact text\r\n"},
                {"id": prefix + "-new-2", "role": "new_requirement", "text": "Второе требование"},
            ]
        )
    return {
        "contract_version": "0.1.0",
        "run_id": prefix + "-run",
        "mode": mode,
        "base_document": {
            "document_id": prefix + "-document",
            "version_id": prefix + "-version",
            "blocks": [
                {"id": prefix + "-heading", "kind": "heading", "text": "# Header\r\n"},
                {"id": prefix + "-anchor", "kind": "paragraph", "text": "Last supported\n"},
                {"id": prefix + "-unsupported", "kind": "unsupported", "text": PRIVATE},
            ],
        },
        "context": {"revision_id": prefix + "-context", "items": context},
    }


def _validated_fixture(request):
    result = _worker().fixture_result(request)
    assert type(result) is dict
    validated = import_module("ara.analysis_contract").validate_result(result, request=request)
    assert validated.result.model_dump(mode="json") == result
    assert "fixture" in result["summary"].lower()
    assert result["findings"] == []
    return result, validated


@pytest.mark.parametrize("mode", ["lint", "merge"])
def test_fixture_is_deterministic_dynamic_and_keeps_exact_input(mode):
    for prefix in ("first", "entirely-different"):
        request = _request(prefix, mode)
        before = deepcopy(request)
        result, validated = _validated_fixture(request)
        assert request == before
        assert _worker().fixture_result(request) == result
        model = import_module("ara.analysis_contract").validate_request(request)
        assert _worker().fixture_result(model) == result
        assert model.model_dump(mode="json") == before
        assert result["run_id"] == request["run_id"]
        assert result["base_version_id"] == request["base_document"]["version_id"]
        assert result["context_revision_id"] == request["context"]["revision_id"]
        coverage = {(entry["source"], entry["id"]): entry for entry in result["coverage"]}
        for block in request["base_document"]["blocks"]:
            entry = coverage[("base", block["id"])]
            assert entry["status"] == ("skipped" if block["kind"] == "unsupported" else "analyzed")
        assert coverage[("context", prefix + "-empty-reference")]["status"] == "skipped"
        assert validated.incomplete_review is True
        assert result["review_status"] == "ready"
        assert result["questions"] == []
        if mode == "lint":
            assert result["change_groups"] == result["change_outcomes"] == []
            continue
        groups = {group["id"]: group for group in result["change_groups"]}
        outcomes = {outcome["context_item_id"]: outcome for outcome in result["change_outcomes"]}
        new_items = [
            item for item in request["context"]["items"] if item["role"] == "new_requirement"
        ]
        assert len(groups) == len(outcomes) == len(new_items)
        for item in new_items:
            outcome = outcomes[item["id"]]
            assert outcome["status"] == "proposed" and len(outcome["change_group_ids"]) == 1
            group = groups[outcome["change_group_ids"][0]]
            assert group["patches"] == [
                {
                    "operation": "insert_after",
                    "target_block_id": prefix + "-anchor",
                    "new_blocks": [{"kind": "paragraph", "text": item["text"]}],
                }
            ]
            assert any(
                evidence["source"] == "context"
                and evidence["id"] == item["id"]
                and evidence["quote"] in item["text"]
                for evidence in group["evidence"]
            )


@pytest.mark.parametrize("unsupported_only", [False, True])
def test_merge_without_supported_anchor_asks_questions(unsupported_only):
    request = _request()
    request["base_document"]["blocks"] = (
        [request["base_document"]["blocks"][-1]] if unsupported_only else []
    )
    result, _ = _validated_fixture(request)
    assert result["review_status"] == "needs_clarification"
    assert result["change_groups"] == []
    assert len(result["questions"]) == len(result["change_outcomes"]) == 2
    assert all(
        outcome["status"] == "needs_clarification" and outcome["question_ids"]
        for outcome in result["change_outcomes"]
    )


def test_empty_new_requirement_is_skipped_out_of_scope_without_fake_evidence():
    request = _request()
    request["context"]["items"] = [{"id": "empty", "role": "new_requirement", "text": ""}]
    result, validated = _validated_fixture(request)
    assert result["review_status"] == "ready"
    assert result["questions"] == result["change_groups"] == []
    assert len(result["change_outcomes"]) == 1
    outcome = result["change_outcomes"][0]
    assert outcome["context_item_id"] == "empty" and outcome["status"] == "out_of_scope"
    assert outcome["evidence"] == [] and outcome["rationale"].strip()
    assert validated.incomplete_review is True


def test_nonempty_whitespace_context_is_analyzed_and_transferred_exactly():
    request = _request()
    request["base_document"]["blocks"] = [request["base_document"]["blocks"][1]]
    whitespace = " \t\r\n"
    request["context"]["items"] = [
        {"id": "blank-reference", "role": "reference", "text": whitespace},
        {"id": "blank-requirement", "role": "new_requirement", "text": whitespace},
    ]
    result, validated = _validated_fixture(request)
    assert all(entry["status"] == "analyzed" for entry in result["coverage"])
    assert validated.incomplete_review is False
    assert result["review_status"] == "ready" and result["questions"] == []
    assert len(result["change_groups"]) == len(result["change_outcomes"]) == 1
    group = result["change_groups"][0]
    outcome = result["change_outcomes"][0]
    assert outcome["context_item_id"] == "blank-requirement"
    assert outcome["status"] == "proposed" and outcome["change_group_ids"] == [group["id"]]
    assert group["patches"] == [
        {
            "operation": "insert_after",
            "target_block_id": "first-anchor",
            "new_blocks": [{"kind": "paragraph", "text": whitespace}],
        }
    ]
    assert (
        group["evidence"]
        == outcome["evidence"]
        == [{"source": "context", "id": "blank-requirement", "quote": whitespace}]
    )


def test_fixture_call_performs_no_file_network_database_or_command_io(monkeypatch):
    worker = _worker()
    request = _request()
    import psycopg
    import sqlalchemy

    def forbidden(*args, **kwargs):
        raise AssertionError("Fixture performed external I/O")

    for target, name in (
        (builtins, "open"),
        (io, "open"),
        (Path, "open"),
        (Path, "read_text"),
        (socket, "socket"),
        (socket, "create_connection"),
        (subprocess, "Popen"),
        (subprocess, "run"),
        (psycopg, "connect"),
        (sqlalchemy, "create_engine"),
    ):
        monkeypatch.setattr(target, name, forbidden)
    result = worker.fixture_result(request)
    assert result["run_id"] == request["run_id"]


def _enqueue(world, key="fixture-run", body=None):
    body = deepcopy(world["body"] if body is None else body)
    with world["client"]() as client:
        response = client.post(
            f"/documents/{world['documents']['own']['id']}/runs",
            json=body,
            headers={"Idempotency-Key": key},
        )
    assert response.status_code == 202, response.text
    return response.json()


def _read_run(world, run_id, *, scope="own", engine=None):
    with world["client"](scope, engine=engine) as client:
        response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _assert_state(run, status, count):
    assert set(run) == RUN_FIELDS
    assert run["status"] == status and run["attempt_count"] == count
    assert run["execution_mode"] == "fixture"
    if status in ("queued", "running"):
        assert run["result"] is run["incomplete_review"] is run["error"] is None
    elif status == "succeeded":
        assert run["result"] is not None and type(run["incomplete_review"]) is bool
        assert run["error"] is None
    else:
        assert run["result"] is run["incomplete_review"] is None
        assert set(run["error"]) == {"code", "message", "retryable"}
        assert run["error"]["retryable"] is False
        assert run["error"]["message"] and PRIVATE not in run["error"]["message"]


def test_http_result_survives_new_engine_replay_and_new_document_version(run_world):
    world = run_world
    version = UUID(world["body"]["base_version_id"])
    with world["engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE document_versions SET import_omissions = CAST(:omissions AS jsonb) "
                "WHERE id = :version"
            ),
            {"version": version, "omissions": json.dumps([{"reason": "Synthetic"}])},
        )
    queued = _enqueue(world)
    _assert_state(queued, "queued", 0)
    assert _read_run(world, queued["run_id"]) == queued
    assert _enqueue(world) == queued
    claim = _worker().claim_next(world["engine"])
    assert str(claim.run_id) == queued["run_id"]
    _assert_state(_read_run(world, claim.run_id), "running", 1)
    append = import_module("ara.documents.storage").append_version
    append(
        world["runtimes"]["own"],
        document_id=UUID(world["documents"]["own"]["id"]),
        expected_version_id=version,
        content_markdown="Changed current\n",
    )
    payload = _worker().fixture_result(claim.request)
    assert _worker().complete_attempt(world["engine"], claim, payload) is True
    done = _read_run(world, claim.run_id)
    _assert_state(done, "succeeded", 1)
    assert done["request"] == queued["request"]
    assert done["base_version_id"] == str(version)
    assert done["result"] == payload and done["incomplete_review"] is True
    replacement = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        assert _read_run(world, claim.run_id, engine=replacement) == done
    finally:
        replacement.dispose()
    assert _enqueue(world) == done
    with world["engine"].connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM analysis_attempts")).scalar_one() == 1
    with world["client"]() as client:
        schema = client.get("/openapi.json").json()
    ref = schema["paths"]["/runs/{run_id}"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    properties = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]["properties"]
    assert set(properties) == RUN_FIELDS


def test_http_failed_response_is_safe_and_replay_does_not_execute_again(run_world):
    world = run_world
    queued = _enqueue(world)
    claim = _worker().claim_next(world["engine"])
    assert _worker().fail_attempt(world["engine"], claim, code="invalid_result") is True
    failed = _read_run(world, queued["run_id"])
    _assert_state(failed, "failed", 1)
    assert failed["error"]["code"] == "invalid_result"
    assert _enqueue(world) == failed


def test_completed_context_remains_private_across_scope_and_owner_transfer(run_world):
    world = run_world
    body = deepcopy(world["body"])
    body["context_items"][0]["text"] = PRIVATE
    queued = _enqueue(world, body=body)
    outcome = _worker().run_once(world["engine"])
    assert outcome.outcome == "succeeded" and str(outcome.run_id) == queued["run_id"]
    _assert_state(_read_run(world, queued["run_id"]), "succeeded", 1)
    for scope in ("peer", "foreign"):
        with world["client"](scope) as client:
            response = client.get(f"/runs/{queued['run_id']}")
            assert response.status_code == 404 and PRIVATE not in response.text
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE projects SET owner_id = :owner WHERE id = :project"),
            {
                "owner": world["owners"]["foreign"],
                "project": world["projects"]["own"],
            },
        )
    runtime = replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
    app = import_module("ara.app").create_app(document_runtime=runtime)
    with (
        world["client"]() as old_owner,
        TestClient(app, raise_server_exceptions=False) as new_owner,
    ):
        for client in (old_owner, new_owner):
            response = client.get(f"/runs/{queued['run_id']}")
            assert response.status_code == 404 and PRIVATE not in response.text
            replay = client.post(
                f"/documents/{world['documents']['own']['id']}/runs",
                json=body,
                headers={"Idempotency-Key": "fixture-run"},
            )
            if client is old_owner:
                assert replay.status_code == 404
            else:
                assert replay.status_code == 202 and replay.json()["run_id"] != queued["run_id"]


def _cli(*arguments, environment=None, timeout=20):
    return subprocess.run(
        [sys.executable, "-m", "ara.worker", *arguments],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), **(environment or {})},
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_real_cli_once_processes_one_run_then_reports_idle(run_world):
    queued = _enqueue(run_world)
    environment = {
        "ARA_ENVIRONMENT": "local",
        "ARA_DATABASE_URL": run_world["engine"].url.render_as_string(hide_password=False),
    }
    completed = _cli("--once", environment=environment)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"outcome": "succeeded", "run_id": queued["run_id"]}
    _assert_state(_read_run(run_world, queued["run_id"]), "succeeded", 1)
    idle = _cli("--once", environment=environment)
    assert idle.returncode == 0, idle.stderr
    assert json.loads(idle.stdout) == {"outcome": "idle", "run_id": None}


@pytest.mark.parametrize("mode", [None, "pilot", "local"])
def test_cli_guard_and_configuration_errors_are_safe(mode):
    environment = {"ARA_DATABASE_URL": PRIVATE}
    if mode is not None:
        environment["ARA_ENVIRONMENT"] = mode
    result = _cli("--once", environment=environment)
    assert result.returncode != 0
    assert result.stderr.strip()
    assert PRIVATE not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr and "No module named" not in result.stderr


def test_local_launcher_refuses_nonlocal_environment_before_database_access():
    launcher = ROOT / "scripts" / "worker.sh"
    assert launcher.is_file()
    result = subprocess.run(
        ["/bin/bash", str(launcher), "--once"],
        cwd=ROOT,
        env={"ARA_ENVIRONMENT": "pilot", "ARA_DATABASE_URL": PRIVATE, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0 and result.stderr.strip()
    assert "local" in result.stderr.lower()
    assert PRIVATE not in result.stdout + result.stderr and "Traceback" not in result.stderr


def test_worker_and_main_imports_are_inert():
    code = """
import builtins, io, socket, subprocess
from pathlib import Path
import psycopg, sqlalchemy
import ara.config, ara.db, ara.models, ara.analysis_contract
def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected external I/O during import")
for target, name in (
    (builtins, "open"), (io, "open"), (Path, "open"), (Path, "read_text"),
    (socket, "socket"), (socket, "create_connection"),
    (subprocess, "Popen"), (subprocess, "run"),
    (psycopg, "connect"), (sqlalchemy, "create_engine"),
    (ara.config, "load_settings"), (ara.db, "create_database_engine"),
):
    setattr(target, name, forbidden)
import ara.worker
import ara.worker.__main__
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
