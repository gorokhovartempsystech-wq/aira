"""Stored payload corruption is a storage error, never a new review draft."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from test_review_api import _body, _count, _error, _get, _ok, _path, _put, _sources


@pytest.mark.parametrize(
    "corruption",
    ["request", "result", "evidence", "run_id", "document_id", "base_id", "context_id", "mode"],
)
def test_review_revalidates_stored_result_and_its_run_identity(review_world, corruption):
    world = review_world
    saved = _ok(_put(world, _body(_get(world))))
    run = world["runs"]["own"]
    request, result = deepcopy(run["request"]), deepcopy(run["result"])
    marker = "SYNTHETIC_CORRUPT_PRIVATE"
    unrelated = str(uuid4())
    mode = request["mode"]
    if corruption == "request":
        request = {"invalid": marker}
    elif corruption == "result":
        result = {"invalid": marker}
    elif corruption == "evidence":
        result["change_groups"][0]["evidence"][0]["quote"] = marker
    elif corruption == "run_id":
        request["run_id"] = result["run_id"] = unrelated
    elif corruption == "document_id":
        request["base_document"]["document_id"] = unrelated
    elif corruption == "base_id":
        request["base_document"]["version_id"] = result["base_version_id"] = unrelated
    elif corruption == "context_id":
        request["context"]["revision_id"] = result["context_revision_id"] = unrelated
    else:
        mode = "lint"
    with world["engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE analysis_runs SET request_payload=CAST(:request AS jsonb), "
                "result_payload=CAST(:result AS jsonb), mode=:mode WHERE id=:id"
            ),
            {
                "request": json.dumps(request),
                "result": json.dumps(result),
                "mode": mode,
                "id": UUID(run["run_id"]),
            },
        )
    before = _sources(world)
    with world["client"]() as client:
        responses = [
            client.get(_path(world)),
            client.get(_path(world), params={"revision_id": saved["revision_id"]}),
            client.put(_path(world), json=_body(saved)),
        ]
    for response in responses:
        _error(response, 500, "storage_error")
        assert marker not in response.text and unrelated not in response.text
    assert _sources(world) == before and _count(world) == 1
    with world["engine"].connect() as connection:
        assert (
            connection.scalar(text("SELECT decisions FROM review_revisions")) == saved["decisions"]
        )
