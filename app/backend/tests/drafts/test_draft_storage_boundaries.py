"""Additional draft failure boundaries in disposable synthetic PostgreSQL databases."""

from importlib import import_module
from uuid import UUID

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import OperationalError

from ara.documents.storage import DocumentError
from tests.acceptance.conftest import apply_migrations as apply_migrations
from tests.acceptance.conftest import empty_pg_engine as empty_pg_engine
from tests.acceptance.conftest import pg_engine as pg_engine
from tests.acceptance.conftest import run_world as run_world

PRIVATE = "SYNTHETIC_DRAFT_PRIVATE_BOUNDARY"


def _arguments(world):
    document = world["documents"]["own"]
    return {
        "document_id": UUID(document["id"]),
        "base_version_id": UUID(document["current_version_id"]),
        "expected_revision": 0,
        "content_markdown": PRIVATE,
    }


def _row(engine):
    with engine.connect() as connection:
        return dict(connection.execute(text("SELECT * FROM document_drafts")).mappings().one())


def _safe_error(error, status, code, retryable=False):
    assert (error.status, error.code, error.retryable) == (status, code, retryable)
    assert PRIVATE not in str(error) + repr(error) + error.message
    assert error.__cause__ is None
    assert error.__suppress_context__ or error.__context__ is None


@pytest.mark.parametrize("operation", ["read", "save"])
@pytest.mark.parametrize("corruption", ["revision", "updated_at", "base_version"])
def test_corrupt_draft_is_rejected_without_overwriting_it(run_world, operation, corruption):
    world = run_world
    api = import_module("ara.drafts")
    arguments = _arguments(world)
    runtime = world["runtimes"]["own"]
    api.save_draft(runtime, **arguments)
    with world["engine"].begin() as connection:
        if corruption == "revision":
            # Removing this check is limited to this test's disposable database.
            constraints = inspect(connection).get_check_constraints("document_drafts")
            revision_checks = [item for item in constraints if "revision" in item["sqltext"]]
            assert len(revision_checks) == 1
            name = connection.dialect.identifier_preparer.quote(revision_checks[0]["name"])
            connection.execute(text(f"ALTER TABLE document_drafts DROP CONSTRAINT {name}"))
            connection.execute(text("UPDATE document_drafts SET revision=0"))
        elif corruption == "updated_at":
            connection.execute(
                text("ALTER TABLE document_drafts ALTER COLUMN updated_at DROP NOT NULL")
            )
            connection.execute(text("UPDATE document_drafts SET updated_at=NULL"))
        else:
            constraints = inspect(connection).get_foreign_keys("document_drafts")
            base_keys = [
                item for item in constraints if "base_version_id" in item["constrained_columns"]
            ]
            assert len(base_keys) == 1
            name = connection.dialect.identifier_preparer.quote(base_keys[0]["name"])
            connection.execute(text(f"ALTER TABLE document_drafts DROP CONSTRAINT {name}"))
            connection.execute(
                text("UPDATE document_drafts SET base_version_id=:base"),
                {"base": UUID(world["documents"]["foreign"]["current_version_id"])},
            )
    before = _row(world["engine"])
    with pytest.raises(DocumentError) as caught:
        if operation == "read":
            api.read_draft(runtime, document_id=arguments["document_id"])
        else:
            api.save_draft(
                runtime,
                **{
                    **arguments,
                    "expected_revision": before["revision"],
                    "content_markdown": "A valid replacement must not hide damaged storage",
                },
            )
    _safe_error(caught.value, 500, "storage_error")
    assert _row(world["engine"]) == before


@pytest.mark.parametrize("operational", [False, True])
def test_read_commit_failure_never_returns_a_snapshot(run_world, operational):
    world = run_world
    api = import_module("ara.drafts")
    arguments = _arguments(world)
    runtime = world["runtimes"]["own"]
    saved = api.save_draft(runtime, **arguments)
    before = _row(world["engine"])

    def fail_commit(connection):
        if operational:
            raise OperationalError(PRIVATE, {"text": PRIVATE}, Exception(PRIVATE))
        raise RuntimeError(PRIVATE)

    event.listen(world["engine"], "commit", fail_commit)
    try:
        with pytest.raises(DocumentError) as caught:
            api.read_draft(runtime, document_id=arguments["document_id"])
        _safe_error(
            caught.value,
            503 if operational else 500,
            "storage_unavailable" if operational else "storage_error",
            operational,
        )
    finally:
        event.remove(world["engine"], "commit", fail_commit)
    assert _row(world["engine"]) == before
    assert api.read_draft(runtime, document_id=arguments["document_id"]) == saved
