"""Additional review boundaries with synthetic data in disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import event, text

from ara.reviews.schemas import PutReview
from ara.reviews.storage import read_review, save_review
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import review_world as review_world
from tests.acceptance.conftest import run_world as run_world


def test_returned_snapshots_do_not_share_mutable_decisions_with_storage(review_world):
    world = review_world
    runtime = world["runtimes"]["own"]
    run_id = UUID(world["runs"]["own"]["run_id"])
    virtual = read_review(runtime, run_id)
    body = PutReview(
        expected_revision_id=None,
        expected_result_fingerprint=virtual.result_fingerprint,
        decisions=[item.model_dump() for item in virtual.decisions],
    )
    saved = save_review(runtime, run_id, body)
    expected = saved.model_dump(mode="json")
    saved.decisions[0].decision = "accepted"
    saved.decisions.pop()
    body.decisions[0].decision = "rejected"
    assert read_review(runtime, run_id).model_dump(mode="json") == expected


@pytest.mark.parametrize("method", ["GET", "PUT"])
@pytest.mark.parametrize("change", ["owner", "project"])
def test_scope_is_rechecked_after_acquiring_run_lock(review_world, method, change):
    world = review_world
    engine = world["engine"]
    path = f"/runs/{world['runs']['own']['run_id']}/review"
    with world["client"]() as client:
        virtual = client.get(path).json()
    body = {
        "expected_revision_id": None,
        "expected_result_fingerprint": virtual["result_fingerprint"],
        "decisions": virtual["decisions"],
    }
    locked, release = Event(), Event()

    def pause_after_run_lock(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lower()
        if (
            normalized.startswith("select")
            and "analysis_runs" in normalized
            and "for update" in normalized
        ):
            locked.set()
            assert release.wait(timeout=10)

    def request():
        with world["client"]() as client:
            return client.request(method, path, **({"json": body} if method == "PUT" else {}))

    event.listen(engine, "after_cursor_execute", pause_after_run_lock)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(request)
            try:
                assert locked.wait(timeout=5)
                with engine.begin() as connection:
                    connection.execute(text("SET LOCAL lock_timeout = '1s'"))
                    if change == "owner":
                        connection.execute(
                            text("UPDATE projects SET owner_id=:owner WHERE id=:id"),
                            {"owner": world["owners"]["foreign"], "id": world["projects"]["own"]},
                        )
                    else:
                        connection.execute(
                            text("UPDATE documents SET project_id=:project WHERE id=:id"),
                            {
                                "project": world["projects"]["peer"],
                                "id": UUID(world["documents"]["own"]["id"]),
                            },
                        )
            finally:
                release.set()
            response = future.result(timeout=10)
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", pause_after_run_lock)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM review_revisions")) == 0
