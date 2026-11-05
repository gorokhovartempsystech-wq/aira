"""Independent HTTP acceptance for immutable review drafts and historical snapshots."""

import hashlib
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

PRIVATE = "SYNTHETIC_REVIEW_PRIVATE_924d"
FIELDS = {
    "run_id",
    "document_id",
    "base_version_id",
    "context_revision_id",
    "execution_mode",
    "revision_id",
    "parent_revision_id",
    "revision_number",
    "created_at",
    "result_fingerprint",
    "decisions",
}


def _path(world, name="own"):
    return f"/runs/{world['runs'][name]['run_id']}/review"


def _body(review):
    return {
        "expected_revision_id": review["revision_id"],
        "expected_result_fingerprint": review["result_fingerprint"],
        "decisions": deepcopy(review["decisions"]),
    }


def _put(world, body, name="own", scope="own"):
    with world["client"](scope) as client:
        return client.put(
            _path(world, name),
            content=json.dumps(body, ensure_ascii=True).encode("ascii"),
            headers={"Content-Type": "application/json"},
        )


def _ok(response):
    assert response.status_code == 200, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    review = response.json()
    assert set(review) == FIELDS
    assert review["execution_mode"] == "fixture"
    for field in ("run_id", "document_id", "base_version_id", "context_revision_id"):
        assert UUID(review[field])
    fingerprint = review["result_fingerprint"]
    assert len(fingerprint) == 64 and all(char in "0123456789abcdef" for char in fingerprint)
    assert type(review["revision_number"]) is int
    if review["revision_number"] == 0:
        assert review["revision_id"] is review["parent_revision_id"] is review["created_at"] is None
    else:
        assert UUID(review["revision_id"])
        assert datetime.fromisoformat(review["created_at"]).utcoffset() is not None
        assert (review["parent_revision_id"] is None) == (review["revision_number"] == 1)
    return review


def _get(world, name="own", *, scope="own", revision_id=None, engine=None):
    params = {} if revision_id is None else {"revision_id": revision_id}
    with world["client"](scope, engine=engine) as client:
        return _ok(client.get(_path(world, name), params=params))


def _error(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["X-ARA-Auth-Mode"] == "local-dev"
    error = response.json()
    assert set(error) == {"code", "message", "retryable", "request_id"}
    assert error["code"] == code and error["retryable"] is False
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str) and error["request_id"]
    assert PRIVATE not in response.text
    return {key: value for key, value in error.items() if key != "request_id"}


def _count(world):
    with world["engine"].connect() as connection:
        return connection.scalar(text("SELECT count(*) FROM review_revisions"))


def _sources(world):
    tables = (
        "users",
        "projects",
        "documents",
        "document_versions",
        "context_revisions",
        "analysis_runs",
        "analysis_attempts",
    )
    with world["engine"].connect() as connection:
        return {
            table: connection.execute(
                text(f"SELECT row_to_json(source) FROM {table} AS source ORDER BY id")
            )
            .scalars()
            .all()
            for table in tables
        }


def _replace_result(world, name, payload):
    run = world["runs"][name]
    import_module("ara.analysis_contract").validate_result(
        payload, request=run["request"], has_import_omissions=run["has_import_omissions"]
    )
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE analysis_runs SET result_payload = CAST(:payload AS jsonb) WHERE id=:id"),
            {"payload": json.dumps(payload), "id": UUID(run["run_id"])},
        )


def test_virtual_review_reads_write_nothing_and_fingerprint_the_source_result(review_world):
    world = review_world
    before = _sources(world)
    first = _get(world)
    assert first == _get(world)
    assert first["revision_number"] == 0
    run = world["runs"]["own"]
    for field in ("run_id", "document_id", "base_version_id", "context_revision_id"):
        assert first[field] == run[field]
    assert first["decisions"] == [
        {"group_id": group["id"], "decision": "pending", "edits": []}
        for group in run["result"]["change_groups"]
    ]
    canonical = json.dumps(
        run["result"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert first["result_fingerprint"] == hashlib.sha256(canonical).hexdigest()
    assert _count(world) == 0 and _sources(world) == before
    with world["client"]() as client:
        assert client.get(f"/runs/{run['run_id']}").json() == run


def test_full_snapshots_keep_draft_choices_exact_edits_and_history_after_new_engine(review_world):
    world = review_world
    original = _sources(world)
    virtual = _get(world)
    body = _body(virtual)
    body["decisions"] = [
        {"group_id": "g3", "decision": "deferred", "edits": []},
        {"group_id": "g2", "decision": "accepted", "edits": []},
        {
            "group_id": "g1",
            "decision": "rejected",
            "edits": [
                {"patch_index": 0, "new_block_index": 1, "text": ""},
                {"patch_index": 0, "new_block_index": 0, "text": "  Точный  текст\r\n\t"},
            ],
        },
    ]
    first = _ok(_put(world, body))
    assert first["revision_number"] == 1
    expected = deepcopy(list(reversed(body["decisions"])))
    expected[0]["edits"].reverse()
    assert first["decisions"] == expected
    # A rejected dependency and unanswered blocking question do not invalidate a draft.
    assert first["decisions"][0]["decision"] == "rejected"
    assert first["decisions"][1]["decision"] == "accepted"
    second_body = _body(first)
    for decision in second_body["decisions"]:
        decision["decision"] = "accepted"
    second = _ok(_put(world, second_body))
    assert second["revision_number"] == 2
    assert second["parent_revision_id"] == first["revision_id"]
    assert second["decisions"] == second_body["decisions"]
    # Accepting conflicting g1/g3 alternatives is also an explicit draft, not an apply.
    replacement = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        assert _get(world, engine=replacement) == second
        assert _get(world, revision_id=first["revision_id"], engine=replacement) == first
        assert _get(world, revision_id=second["revision_id"], engine=replacement) == second
    finally:
        replacement.dispose()
    first["decisions"][0]["edits"][0]["text"] = "Only a caller copy"
    assert _get(world, revision_id=first["revision_id"])["decisions"] == expected
    assert _count(world) == 2 and _sources(world) == original


def test_review_keeps_old_base_after_current_document_version_changes(review_world):
    world = review_world
    old = _get(world)
    import_module("ara.documents.storage").append_version(
        world["runtimes"]["own"],
        document_id=UUID(old["document_id"]),
        expected_version_id=UUID(old["base_version_id"]),
        content_markdown="New current version\n",
    )
    before = _sources(world)
    assert _get(world) == old
    saved = _ok(_put(world, _body(old)))
    assert saved["base_version_id"] == old["base_version_id"]
    assert saved["result_fingerprint"] == old["result_fingerprint"]
    assert _sources(world) == before


def test_strict_shape_group_membership_indices_and_text_reject_without_writes(review_world):
    world = review_world
    virtual = _get(world)
    base = _body(virtual)
    base["decisions"][0]["edits"] = [{"patch_index": 0, "new_block_index": 0, "text": "valid"}]
    variants = []

    def change(path, value=None, *, delete=False):
        body = deepcopy(base)
        node = body
        for key in path[:-1]:
            node = node[key]
        if delete:
            del node[path[-1]]
        else:
            node[path[-1]] = value
        variants.append(body)

    for field in base:
        change((field,), delete=True)
    for field in ("group_id", "decision", "edits"):
        change(("decisions", 0, field), delete=True)
    for field in ("patch_index", "new_block_index", "text"):
        change(("decisions", 0, "edits", 0, field), delete=True)
    for field in ("owner_id", "revision_id", "result", "patches"):
        change((field,), PRIVATE)
    change(("decisions", 0, "evidence"), [])
    change(("decisions", 0, "edits", 0, "kind"), "code")
    for group_id in ("unknown", " g1 ", 1, True):
        change(("decisions", 0, "group_id"), group_id)
    change(("decisions",), base["decisions"][:-1])
    change(("decisions",), base["decisions"] + [deepcopy(base["decisions"][0])])
    for decision in ("accept", " accepted ", True, None):
        change(("decisions", 0, "decision"), decision)
    for index in (-1, True, 0.0, "0", 999):
        for field in ("patch_index", "new_block_index"):
            change(("decisions", 0, "edits", 0, field), index)
    change(("decisions", 0, "edits"), base["decisions"][0]["edits"] * 2)
    change(("decisions", 2, "edits"), deepcopy(base["decisions"][0]["edits"]))
    for invalid in (None, 1, True, PRIVATE + "\x00", PRIVATE + "\ud800"):
        change(("decisions", 0, "edits", 0, "text"), invalid)
    for value in (None, {}, "decisions"):
        change(("decisions",), value)
        change(("decisions", 0, "edits"), value)
    for value in (False, 12, "not-a-uuid"):
        change(("expected_revision_id",), value)
    for value in (None, 123, "f" * 63, "A" * 64, "z" * 64):
        change(("expected_result_fingerprint",), value)
    before = _sources(world)
    for number, body in enumerate(variants):
        response = _put(world, body)
        assert response.status_code == 422, f"strict body variant {number}: {response.status_code}"
        _error(response, 422, "validation_error")
    with world["client"]() as client:
        _error(client.get(_path(world), params={"revision_id": "invalid"}), 422, "validation_error")
    assert _count(world) == 0 and _sources(world) == before
    assert _get(world) == virtual


@pytest.mark.parametrize("limit", ["decisions", "edits", "text"])
def test_real_upper_bound_is_accepted_and_one_over_is_rejected(review_world, limit):
    world = review_world
    for name, overflow in (("own", False), ("second", True)):
        payload = deepcopy(world["runs"][name]["result"])
        if limit == "decisions":
            for index in range(5000 + overflow - len(payload["change_groups"])):
                group = deepcopy(payload["change_groups"][0])
                group["id"] = f"extra-{index}"
                payload["change_groups"].append(group)
        elif limit == "edits":
            payload["change_groups"][0]["patches"][0]["new_blocks"] = [
                {"kind": "paragraph", "text": "Synthetic"} for _ in range(5000 + overflow)
            ]
        _replace_result(world, name, payload)
        virtual = _get(world, name)
        body = _body(virtual)
        if limit == "edits":
            body["decisions"][0]["edits"] = [
                {"patch_index": 0, "new_block_index": index, "text": ""}
                for index in range(5000 + overflow)
            ]
        elif limit == "text":
            body["decisions"][0]["edits"] = [
                {"patch_index": 0, "new_block_index": 0, "text": "я" * 500_000},
                {"patch_index": 0, "new_block_index": 1, "text": " " * (500_000 + overflow)},
            ]
        if overflow:
            _error(_put(world, body, name), 422, "validation_error")
            assert _get(world, name) == virtual
        else:
            assert _ok(_put(world, body, name))["decisions"] == body["decisions"]
    assert _count(world) == 1


def test_wrong_fingerprint_and_changed_valid_result_do_not_reinterpret_saved_edits(review_world):
    world = review_world
    virtual = _get(world)
    wrong = _body(virtual)
    wrong["expected_result_fingerprint"] = "0" * 64
    wrong["decisions"][0]["group_id"] = "unknown"
    _error(_put(world, wrong), 409, "review_result_changed")
    assert _count(world) == 0
    saved = _ok(_put(world, _body(virtual)))
    replacement = deepcopy(world["runs"]["own"]["result"])
    replacement["summary"] += " Changed valid synthetic result"
    _replace_result(world, "own", replacement)
    with world["client"]() as client:
        _error(client.get(_path(world)), 409, "review_result_changed")
        _error(
            client.get(_path(world), params={"revision_id": saved["revision_id"]}),
            409,
            "review_result_changed",
        )
    _error(_put(world, _body(saved)), 409, "review_result_changed")
    updated = _body(saved)
    updated["expected_result_fingerprint"] = hashlib.sha256(
        json.dumps(replacement, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    _error(_put(world, updated), 409, "review_result_changed")
    assert _count(world) == 1
    with world["engine"].connect() as connection:
        assert (
            connection.scalar(text("SELECT decisions FROM review_revisions")) == saved["decisions"]
        )


def test_unknown_foreign_run_and_foreign_revision_have_the_same_not_found(review_world):
    world = review_world
    virtual = _get(world)
    own = _ok(_put(world, _body(virtual)))
    second = _ok(_put(world, _body(_get(world, "second")), "second"))
    errors = []
    with world["client"]() as client:
        for run_id in (
            str(uuid4()),
            world["runs"]["peer"]["run_id"],
            world["runs"]["foreign"]["run_id"],
        ):
            path = f"/runs/{run_id}/review"
            errors.append(_error(client.get(path), 404, "not_found"))
            wrong = _body(virtual)
            wrong["expected_result_fingerprint"] = "0" * 64
            errors.append(_error(client.put(path, json=wrong), 404, "not_found"))
        for revision_id in (str(uuid4()), second["revision_id"]):
            errors.append(
                _error(
                    client.get(_path(world), params={"revision_id": revision_id}), 404, "not_found"
                )
            )
    for scope in ("peer", "foreign"):
        with world["client"](scope) as client:
            errors.append(_error(client.get(_path(world)), 404, "not_found"))
            errors.append(_error(client.put(_path(world), json=_body(own)), 404, "not_found"))
    assert all(error == errors[0] for error in errors)
    assert _count(world) == 2 and _get(world) == own


def test_project_transfer_hides_prior_creator_review_from_both_owners(review_world):
    world = review_world
    body = _body(_get(world))
    body["decisions"][0]["edits"] = [{"patch_index": 0, "new_block_index": 0, "text": PRIVATE}]
    saved = _ok(_put(world, body))
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
            {"owner": world["owners"]["foreign"], "project": world["projects"]["own"]},
        )
    runtime = replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
    app = import_module("ara.app").create_app(document_runtime=runtime)
    with (
        world["client"]() as old_owner,
        TestClient(app, raise_server_exceptions=False) as new_owner,
    ):
        for client in (old_owner, new_owner):
            _error(client.get(_path(world)), 404, "not_found")
            _error(
                client.get(_path(world), params={"revision_id": saved["revision_id"]}),
                404,
                "not_found",
            )
            _error(client.put(_path(world), json=_body(saved)), 404, "not_found")
    assert _count(world) == 1


def test_queued_running_and_failed_runs_are_not_reviewable(review_world):
    world = review_world
    with world["client"]() as client:
        response = client.post(
            f"/documents/{world['documents']['own']['id']}/runs",
            json=world["body"],
            headers={"Idempotency-Key": "review-not-ready"},
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        path = f"/runs/{run_id}/review"
        body = {
            "expected_revision_id": None,
            "expected_result_fingerprint": "0" * 64,
            "decisions": [],
        }

        def not_ready():
            _error(client.get(path), 409, "review_not_ready")
            _error(client.put(path, json=body), 409, "review_not_ready")

        not_ready()
        worker = import_module("ara.worker")
        claim = worker.claim_next(world["engine"])
        assert str(claim.run_id) == run_id
        not_ready()
        assert worker.fail_attempt(world["engine"], claim, code="invalid_result")
        not_ready()
    assert _count(world) == 0


def test_empty_analysis_result_allows_an_empty_review_snapshot(review_world):
    world = review_world
    with world["client"]() as client:
        response = client.post(
            f"/documents/{world['documents']['own']['id']}/runs",
            json={**world["body"], "mode": "lint", "context_items": []},
            headers={"Idempotency-Key": "review-empty-lint"},
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
    assert import_module("ara.worker").run_once(world["engine"]).outcome == "succeeded"
    with world["client"]() as client:
        virtual = _ok(client.get(f"/runs/{run_id}/review"))
        assert virtual["decisions"] == []
        saved = _ok(client.put(f"/runs/{run_id}/review", json=_body(virtual)))
        assert saved["revision_number"] == 1 and saved["decisions"] == []
    assert _count(world) == 1
