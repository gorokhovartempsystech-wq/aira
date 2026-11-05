"""Synthetic PostgreSQL tests for enqueue races, access locks and saved inputs."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError

from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world


def _post(world, body=None):
    with world["client"]() as client:
        return client.post(
            f"/documents/{world['documents']['own']['id']}/runs",
            json=world["body"] if body is None else body,
            headers={"Idempotency-Key": "boundary-key"},
        )


@pytest.mark.parametrize("same_body", [True, False])
def test_unique_constraint_race_rolls_back_losing_context(run_world, same_body):
    world = run_world
    barrier = Barrier(2)

    def before_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO analysis_runs"):
            # Force both transactions past the initial key lookup and context
            # insert, exercising the actual unique-violation recovery path.
            barrier.wait(timeout=10)

    bodies = [deepcopy(world["body"]), deepcopy(world["body"])]
    if not same_body:
        bodies[1]["context_items"][0]["text"] += " Changed"
    event.listen(world["engine"], "before_cursor_execute", before_insert)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_post, world, body) for body in bodies]
            responses = [future.result(timeout=20) for future in futures]
    finally:
        event.remove(world["engine"], "before_cursor_execute", before_insert)
    assert sorted(response.status_code for response in responses) == (
        [202, 202] if same_body else [202, 409]
    )
    if same_body:
        assert responses[0].json() == responses[1].json()
    else:
        error = next(response.json() for response in responses if response.status_code == 409)
        assert error["code"] == "idempotency_conflict"
    with world["engine"].connect() as connection:
        for table in ("context_revisions", "analysis_runs"):
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 1


@pytest.mark.parametrize("boundary", ["project_owner", "document_project"])
def test_access_boundary_is_locked_until_enqueue_commits(run_world, boundary):
    world = run_world
    observed = []

    def try_move(connection, cursor, statement, parameters, context, executemany):
        if not statement.startswith("INSERT INTO analysis_runs"):
            return
        with world["engine"].connect() as outsider:
            outsider.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError) as caught:
                if boundary == "project_owner":
                    outsider.execute(
                        text("UPDATE projects SET owner_id = :owner WHERE id = :project"),
                        {"owner": world["owners"]["foreign"], "project": world["projects"]["own"]},
                    )
                else:
                    outsider.execute(
                        text("UPDATE documents SET project_id = :project WHERE id = :document"),
                        {
                            "project": world["projects"]["peer"],
                            "document": UUID(world["documents"]["own"]["id"]),
                        },
                    )
            assert caught.value.orig.sqlstate == "55P03"
            observed.append(boundary)

    event.listen(world["engine"], "before_cursor_execute", try_move)
    try:
        assert _post(world).status_code == 202
    finally:
        event.remove(world["engine"], "before_cursor_execute", try_move)
    assert observed == [boundary]


def test_snapshot_and_fingerprint_are_persisted_not_reconstructed(run_world):
    world = run_world
    body = deepcopy(world["body"])
    body["base_version_id"] = body["base_version_id"].upper()
    body["context_items"][0]["text"] = "  Точный текст\r\n"
    response = _post(world, body)
    assert response.status_code == 202
    saved = response.json()
    canonical = {
        "document_id": world["documents"]["own"]["id"],
        **body,
        "base_version_id": str(UUID(body["base_version_id"])),
    }
    expected = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    with world["engine"].begin() as connection:
        assert connection.scalar(text("SELECT request_fingerprint FROM analysis_runs")) == expected
        # Deliberate out-of-band corruption must not cause GET/replay to rebuild
        # a previously committed snapshot from mutable source records.
        connection.execute(
            text(
                "UPDATE document_versions SET blocks = '[]', import_omissions = '[{}]' "
                "WHERE id = :id"
            ),
            {"id": UUID(body["base_version_id"])},
        )
        connection.execute(text("UPDATE context_revisions SET items = '[]'"))
    with world["client"]() as client:
        assert client.get(f"/runs/{saved['run_id']}").json() == saved
    body["base_version_id"] = body["base_version_id"].lower()
    assert _post(world, body).json() == saved
