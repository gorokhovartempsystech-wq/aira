"""Independent HTTP acceptance for queued runs and immutable request snapshots."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

PRIVATE = "SYNTHETIC_PRIVATE_RUN_CONTENT_329b"


def _body(world, document="own"):
    body = deepcopy(world["body"])
    body["base_version_id"] = world["documents"][document]["current_version_id"]
    return body


def _post(world, *, document="own", scope="own", body=None, key="run-key", headers=None):
    if body is None:
        body = _body(world, document)
    if headers is None:
        headers = [] if key is None else [("Idempotency-Key", key)]
    with world["client"](scope) as client:
        return client.post(
            f"/documents/{world['documents'][document]['id']}/runs",
            content=json.dumps(body, ensure_ascii=True).encode("ascii"),
            headers=[("Content-Type", "application/json"), *headers],
        )


def _created(response):
    assert response.status_code == 202, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    run = response.json()
    assert set(run) == {
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
    for field in ("run_id", "document_id", "base_version_id", "context_revision_id"):
        assert UUID(run[field])
    assert run["status"] == "queued"
    assert run["execution_mode"] == "fixture"
    assert datetime.fromisoformat(run["created_at"]).utcoffset() is not None
    assert type(run["has_import_omissions"]) is bool
    assert run["attempt_count"] == 0
    assert run["result"] is None
    assert run["incomplete_review"] is None
    assert run["error"] is None
    return run


def _error(response, status, code, forbidden=()):
    assert response.status_code == status, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    body = response.json()
    assert set(body) == {"code", "message", "retryable", "request_id"}
    assert body["code"] == code
    assert body["retryable"] is False
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["request_id"], str) and body["request_id"]
    for value in (PRIVATE, *forbidden):
        assert value not in response.text
    return {key: value for key, value in body.items() if key != "request_id"}


def _counts(world):
    with world["engine"].connect() as connection:
        return connection.execute(
            text(
                "SELECT (SELECT count(*) FROM analysis_runs), "
                "(SELECT count(*) FROM context_revisions)"
            )
        ).one()


def test_snapshot_replay_and_old_base_survive_new_engine_and_current_version(run_world):
    world = run_world
    body = _body(world)
    run = _created(_post(world, body=body))
    document = world["documents"]["own"]
    with world["client"]() as client:
        version = client.get(
            f"/documents/{document['id']}/versions/{body['base_version_id']}"
        ).json()
        assert client.get(f"/runs/{run['run_id']}").status_code == 200
        assert client.get(f"/runs/{run['run_id']}").json() == run
    assert run["mode"] == body["mode"]
    assert run["document_id"] == document["id"]
    assert run["base_version_id"] == body["base_version_id"]
    assert run["has_import_omissions"] is False
    assert run["request"] == {
        "contract_version": "0.1.0",
        "run_id": run["run_id"],
        "mode": body["mode"],
        "base_document": {
            "document_id": document["id"],
            "version_id": body["base_version_id"],
            "blocks": version["blocks"],
        },
        "context": {"revision_id": run["context_revision_id"], "items": body["context_items"]},
    }
    validator = import_module("ara.analysis_contract").validate_request
    assert validator(run["request"]).model_dump(mode="json") == run["request"]
    reordered = dict(reversed(list(body.items())))
    reordered["context_items"] = [
        dict(reversed(list(item.items()))) for item in body["context_items"]
    ]
    assert _created(_post(world, body=reordered)) == run
    append = import_module("ara.documents.storage").append_version
    next_version = append(
        world["runtimes"]["own"],
        document_id=UUID(document["id"]),
        expected_version_id=UUID(body["base_version_id"]),
        content_markdown="Changed current\n",
    )
    _error(
        _post(world, body={**body, "base_version_id": str(next_version.id)}),
        409,
        "idempotency_conflict",
        (run["run_id"],),
    )
    assert _counts(world) == (1, 1)
    replacement = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        with world["client"](engine=replacement) as client:
            assert client.get(f"/runs/{run['run_id']}").json() == run
            replay = client.post(
                f"/documents/{document['id']}/runs",
                json=body,
                headers={"Idempotency-Key": "run-key"},
            )
            assert _created(replay) == run
    finally:
        replacement.dispose()
    old_base = _created(_post(world, body=body, key="another-key"))
    assert old_base["base_version_id"] == body["base_version_id"]
    assert old_base["request"]["base_document"] == run["request"]["base_document"]
    assert _counts(world) == (2, 2)
    with world["engine"].connect() as connection:
        saved = connection.execute(
            text(
                "SELECT r.request_payload, c.items, c.owner_id, c.document_id "
                "FROM analysis_runs r JOIN context_revisions c ON c.id = r.context_revision_id "
                "WHERE r.id = :id"
            ),
            {"id": UUID(run["run_id"])},
        ).one()
        assert tuple(saved) == (
            run["request"],
            body["context_items"],
            world["owners"]["own"],
            UUID(document["id"]),
        )


def test_owner_scoped_key_rejects_changed_payload_document_and_project(run_world):
    world = run_world
    key = "private-idempotency-key-52"
    original = _body(world)
    original["context_items"].append({"id": "ref-1", "role": "reference", "text": PRIVATE})
    first = _created(_post(world, body=original, key=key))
    variants = []
    changed_text = deepcopy(original)
    changed_text["context_items"][0]["text"] += " "
    variants.append(changed_text)
    changed_order = deepcopy(original)
    changed_order["context_items"].reverse()
    variants.append(changed_order)
    variants.append({**original, "mode": "lint", "context_items": []})
    for body in variants:
        _error(
            _post(world, body=body, key=key), 409, "idempotency_conflict", (key, first["run_id"])
        )
    for document, scope in (("second", "own"), ("peer", "peer")):
        _error(
            _post(world, document=document, scope=scope, key=key),
            409,
            "idempotency_conflict",
            (key, first["run_id"]),
        )
    foreign = _created(_post(world, document="foreign", scope="foreign", key=key))
    assert foreign["run_id"] != first["run_id"]
    assert _counts(world) == (2, 2)


def test_access_is_checked_before_replay_or_conflict(run_world):
    world = run_world
    first = _created(_post(world))
    foreign = _created(_post(world, document="foreign", scope="foreign", key="foreign"))
    peer = _created(_post(world, document="peer", scope="peer", key="peer"))
    errors = []
    with world["client"]() as client:
        for run_id in (foreign["run_id"], peer["run_id"], str(uuid4())):
            errors.append(_error(client.get(f"/runs/{run_id}"), 404, "not_found"))
        for document, version in (
            (
                world["documents"]["foreign"]["id"],
                world["documents"]["foreign"]["current_version_id"],
            ),
            (world["documents"]["peer"]["id"], world["documents"]["peer"]["current_version_id"]),
            (str(uuid4()), str(uuid4())),
            (world["documents"]["own"]["id"], world["documents"]["second"]["current_version_id"]),
        ):
            response = client.post(
                f"/documents/{document}/runs",
                json={**_body(world), "base_version_id": version},
                headers={"Idempotency-Key": "run-key"},
            )
            errors.append(_error(response, 404, "not_found", (first["run_id"],)))
    assert all(error == errors[0] for error in errors)
    assert _counts(world) == (3, 3)


def test_project_transfer_does_not_disclose_old_creator_context(run_world):
    world = run_world
    first = _created(_post(world))
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE projects SET owner_id = :owner WHERE id = :project"),
            {"owner": world["owners"]["foreign"], "project": world["projects"]["own"]},
        )
    with world["client"]() as client:
        _error(client.get(f"/runs/{first['run_id']}"), 404, "not_found")
    _error(_post(world), 404, "not_found")
    new_owner_runtime = replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
    app = import_module("ara.app").create_app(document_runtime=new_owner_runtime)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/documents").status_code == 200
        _error(client.get(f"/runs/{first['run_id']}"), 404, "not_found")
    assert _counts(world) == (1, 1)


def test_lint_accepts_reference_context_and_valid_ascii_key(run_world):
    body = _body(run_world)
    body.update(
        mode="lint", context_items=[{"id": " ref-1 ", "role": "reference", "text": "  Reference\n"}]
    )
    run = _created(_post(run_world, body=body, key="A.z_0:-" + "x" * 121))
    assert run["mode"] == "lint"
    assert run["request"]["context"]["items"] == body["context_items"]


def test_invalid_input_and_idempotency_headers_return_safe_422(run_world):
    world = run_world
    bodies = [{}]
    for replacement in (
        {"mode": "invalid"},
        {"mode": "lint"},
        {"base_version_id": "invalid"},
        {"base_version_id": 7},
        {"context_items": None},
        {"context_items": {}},
        {"context_items": []},
    ):
        bodies.append({**_body(world), **replacement})
    for field in ("owner", "owner_id", "run_id", "status", "result", "blocks", "execution_mode"):
        bodies.append({**_body(world), field: PRIVATE})
    for replacement in (
        {"id": " "},
        {"id": "x" * 201},
        {"id": 7},
        {"role": "invalid"},
        {"role": "reference"},
        {"text": " \r\n"},
        {"text": 7},
        {"text": "\x00"},
        {"text": "\ud800"},
        {"extra": PRIVATE},
    ):
        body = _body(world)
        body["context_items"][0].update(replacement)
        bodies.append(body)
    duplicate = _body(world)
    duplicate["context_items"] *= 2
    bodies.append(duplicate)
    too_many = _body(world)
    too_many["context_items"] = [
        {"id": f"req-{index}", "role": "new_requirement", "text": "text"} for index in range(101)
    ]
    bodies.append(too_many)
    too_long = _body(world)
    too_long["context_items"] = [
        {"id": f"req-{index}", "role": "new_requirement", "text": "x" * 500_001}
        for index in range(2)
    ]
    bodies.append(too_long)
    for body in bodies:
        _error(_post(world, body=body), 422, "validation_error")
    for key in (None, "", " ", "key with spaces", "x" * 129, "bad/key"):
        _error(_post(world, key=key), 422, "validation_error")
    for headers in (
        [("Idempotency-Key", "same"), ("Idempotency-Key", "same")],
        [(b"Idempotency-Key", b"\xc3\xbc")],
    ):
        _error(_post(world, headers=headers), 422, "validation_error")
    assert _counts(world) == (0, 0)


@pytest.mark.parametrize("source", ["unsupported", "importer_omission"])
def test_backend_snapshot_hides_unsupported_text_and_preserves_omission_flags(run_world, source):
    world = run_world
    with world["client"]() as client:
        if source == "unsupported":
            created = client.post(
                "/documents",
                json={"title": "Unsupported", "content_markdown": f"```text\n{PRIVATE}"},
            )
            assert created.status_code == 201
            world["documents"]["own"] = created.json()
        document = world["documents"]["own"]
        path = f"/documents/{document['id']}/versions/{document['current_version_id']}"
        original = client.get(path).json()
    omissions = [] if source == "unsupported" else [{"reason": "Synthetic importer omission"}]
    with world["engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE document_versions SET import_omissions = CAST(:value AS jsonb) "
                "WHERE id = :id"
            ),
            {"value": json.dumps(omissions), "id": UUID(document["current_version_id"])},
        )
    run = _created(_post(world))
    assert run["has_import_omissions"] is True
    expected_blocks = deepcopy(original["blocks"])
    for block in expected_blocks:
        if block["kind"] == "unsupported":
            block["text"] = "[Unsupported block retained in source version]"
    assert run["request"]["base_document"]["blocks"] == expected_blocks
    if source == "unsupported":
        assert PRIVATE not in json.dumps(run)
    with world["client"]() as client:
        assert client.get(path).json()["blocks"] == original["blocks"]
        assert client.get(f"/runs/{run['run_id']}").json() == run
