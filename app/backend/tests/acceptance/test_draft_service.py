"""Independent acceptance of D01-01's exact, owner-scoped Python draft service."""

from dataclasses import replace
from datetime import datetime
from importlib import import_module
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

PRIVATE = "SYNTHETIC_DRAFT_PRIVATE_759c"
FIELDS = {"document_id", "base_version_id", "revision", "content_markdown", "updated_at"}
SOURCE_TABLES = (
    "users",
    "projects",
    "documents",
    "document_versions",
    "context_revisions",
    "analysis_runs",
    "analysis_attempts",
    "review_revisions",
)
MAX_EXPECTED_REVISION = 9223372036854775806


def _api():
    # Collection must succeed before the implementation exists.
    return import_module("ara.drafts")


def _ids(world, name="own"):
    document = world["documents"][name]
    return UUID(document["id"]), UUID(document["current_version_id"])


def _save(world, revision=0, content=PRIVATE, *, name="own", scope="own", base=None):
    document, original_base = _ids(world, name)
    return _api().save_draft(
        world["runtimes"][scope],
        document_id=document,
        expected_revision=revision,
        base_version_id=original_base if base is None else base,
        content_markdown=content,
    )


def _read(world, *, name="own", scope="own"):
    return _api().read_draft(world["runtimes"][scope], document_id=_ids(world, name)[0])


def _sources(engine):
    with engine.connect() as connection:
        return {
            table: connection.execute(
                text(f"SELECT row_to_json(source) FROM {table} AS source ORDER BY id")
            )
            .scalars()
            .all()
            for table in SOURCE_TABLES
        }


def _drafts(engine):
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM document_drafts ORDER BY document_id")
            ).mappings()
        ]


def _failure(operation, status, code):
    error_type = import_module("ara.documents.storage").DocumentError
    with pytest.raises(error_type) as caught:
        operation()
    error = caught.value
    assert (error.status, error.code, error.retryable) == (status, code, False)
    assert isinstance(error.message, str) and error.message
    assert str(error) == error.message
    assert PRIVATE not in error.message
    if status == 404:
        assert error.message == import_module("ara.documents.storage")._not_found().message
    return error.message


def _snapshot(snapshot, document, base, revision, content):
    assert isinstance(snapshot, _api().DraftSnapshot)
    assert isinstance(snapshot, BaseModel)
    assert set(type(snapshot).model_fields) == FIELDS
    assert set(snapshot.model_dump()) == FIELDS
    assert isinstance(snapshot.document_id, UUID) and snapshot.document_id == document
    assert isinstance(snapshot.base_version_id, UUID) and snapshot.base_version_id == base
    assert type(snapshot.revision) is int and snapshot.revision == revision > 0
    assert type(snapshot.content_markdown) is str and snapshot.content_markdown == content
    assert isinstance(snapshot.updated_at, datetime)
    assert snapshot.updated_at.utcoffset() is not None


def test_absent_draft_read_is_none_and_never_writes(run_world):
    world = run_world
    before = _sources(world["engine"])
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    event.listen(world["engine"], "before_cursor_execute", observe)
    try:
        for name, scope in (("own", "own"), ("second", "own"), ("peer", "peer")):
            assert _read(world, name=name, scope=scope) is None
            assert _read(world, name=name, scope=scope) is None
    finally:
        event.remove(world["engine"], "before_cursor_execute", observe)
    assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "MERGE")) for sql in statements)
    assert _drafts(world["engine"]) == []
    assert _sources(world["engine"]) == before


def test_detached_frozen_five_field_snapshot_restores_with_new_engine(review_world, monkeypatch):
    world = review_world
    document, base = _ids(world)
    with world["client"]() as client:
        path = f"/runs/{world['runs']['own']['run_id']}/review"
        response = client.get(path)
        assert response.status_code == 200, response.text
        review = response.json()
        saved_review = client.put(
            path,
            json={
                "expected_revision_id": review["revision_id"],
                "expected_result_fingerprint": review["result_fingerprint"],
                "decisions": review["decisions"],
            },
        )
        assert saved_review.status_code == 200, saved_review.text
    before = _sources(world["engine"])
    assert all(before.values()), "Every protected source table must contain synthetic evidence"

    def unexpected_dispose(*args, **kwargs):
        pytest.fail("The draft service does not own the caller's engine")

    with monkeypatch.context() as patch:
        patch.setattr(world["engine"], "dispose", unexpected_dispose)
        assert _read(world) is None
        first = _save(world, content="# Черновик 🧪\r\n\r\n  Exact text\t\n```unfinished")
        _snapshot(first, document, base, 1, "# Черновик 🧪\r\n\r\n  Exact text\t\n```unfinished")
        first_dump = first.model_dump()
        for field, value in (
            ("document_id", uuid4()),
            ("base_version_id", uuid4()),
            ("revision", 99),
            ("content_markdown", "Attempted mutation"),
            ("updated_at", datetime.now(first.updated_at.tzinfo)),
        ):
            with pytest.raises(ValidationError):
                setattr(first, field, value)
        with pytest.raises(ValidationError):
            _api().DraftSnapshot(**first_dump, owner_id=world["owners"]["own"])
        detached_dump = first.model_dump()
        detached_dump["content_markdown"] = "Only a caller-owned copy"
        second = _save(world, revision=1, content="Entire replacement\r\n")
        _snapshot(second, document, base, 2, "Entire replacement\r\n")
        assert first.model_dump() == first_dump
        assert _read(world).model_dump() == second.model_dump()
        with world["engine"].connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1

    replacement = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        runtime = replace(world["runtimes"]["own"], engine=replacement)
        restored = _api().read_draft(runtime, document_id=document)
        assert restored.model_dump() == second.model_dump()
    finally:
        replacement.dispose()
    assert _drafts(world["engine"]) == [second.model_dump()]
    assert _sources(world["engine"]) == before


@pytest.mark.parametrize(
    "content",
    [
        "",
        " \t\r\n \n\t",
        "e\u0301 / é / 日本語 / 🧑🏽‍💻 / \ufeff / \u2028",
        "# Heading\r\n\r\nParagraph  \r\n- item\r\n",
        "```python\r\nif True:\n  unfinished\r\n",
        "x" * 1_000_001 + "\r\nЯ🧪",
    ],
    ids=["empty", "whitespace", "unicode", "crlf", "unclosed-markdown", "over-million"],
)
def test_every_supported_text_restores_exactly_after_a_new_engine(run_world, content):
    world = run_world
    document, base = _ids(world)
    saved = _save(world, content=content)
    _snapshot(saved, document, base, 1, content)
    replacement = create_engine(world["engine"].url, poolclass=NullPool, hide_parameters=True)
    try:
        restored = _api().read_draft(
            replace(world["runtimes"]["own"], engine=replacement), document_id=document
        )
        _snapshot(restored, document, base, 1, content)
        assert restored.model_dump() == saved.model_dump()
    finally:
        replacement.dispose()


def test_compare_and_swap_rejects_stale_replay_and_replaces_the_full_text(run_world):
    world = run_world
    before = _sources(world["engine"])
    messages = {_failure(lambda: _save(world, revision=1), 409, "draft_conflict")}
    assert _drafts(world["engine"]) == []
    first = _save(world, content="Original text with a suffix")
    for expected in (0, 2, MAX_EXPECTED_REVISION):
        messages.add(
            _failure(
                lambda: _save(world, revision=expected, content=first.content_markdown),
                409,
                "draft_conflict",
            )
        )
        assert _read(world).model_dump() == first.model_dump()
    same = _save(world, revision=1, content=first.content_markdown)
    assert same.revision == 2
    shortened = _save(world, revision=2, content="Short")
    assert shortened.revision == 3 and shortened.content_markdown == "Short"
    for expected in (0, 1, 2, 4):
        messages.add(
            _failure(
                lambda: _save(world, revision=expected, content="Short"), 409, "draft_conflict"
            )
        )
        assert _read(world).model_dump() == shortened.model_dump()
    assert len(messages) == 1
    assert _sources(world["engine"]) == before


def test_older_base_remains_valid_and_base_changes_only_when_explicitly_saved(run_world):
    world = run_world
    document, old_base = _ids(world)
    first = _save(world)
    latest = import_module("ara.documents.storage").append_version(
        world["runtimes"]["own"],
        document_id=document,
        expected_version_id=old_base,
        content_markdown="A separately saved newer version\n",
    )
    before = _sources(world["engine"])
    assert _read(world).model_dump() == first.model_dump()
    second = _save(world, revision=1, content="Still based on the older version")
    _snapshot(second, document, old_base, 2, "Still based on the older version")
    third = _save(world, revision=2, content="Explicit new base", base=latest.id)
    _snapshot(third, document, latest.id, 3, "Explicit new base")
    fourth = _save(world, revision=3, content="Explicit older base", base=old_base)
    _snapshot(fourth, document, old_base, 4, "Explicit older base")
    assert _sources(world["engine"]) == before


def test_unknown_or_other_document_base_is_generic_not_found_before_revision_conflict(run_world):
    world = run_world
    saved = _save(world)
    before = _sources(world["engine"])
    messages = set()
    for base in (uuid4(), *(_ids(world, name)[1] for name in ("second", "peer", "foreign"))):
        for expected in (0, 1, 5):
            message = _failure(lambda: _save(world, revision=expected, base=base), 404, "not_found")
            assert str(base) not in message
            messages.add(message)
            assert _read(world).model_dump() == saved.model_dump()
    assert len(messages) == 1
    assert _sources(world["engine"]) == before


def test_document_scope_precedes_base_and_revision_checks_for_read_and_save(run_world):
    world = run_world
    for name, scope in (("own", "own"), ("peer", "peer"), ("foreign", "foreign")):
        _save(world, name=name, scope=scope)
    before_sources, before_drafts = _sources(world["engine"]), _drafts(world["engine"])
    own_document, own_base = _ids(world)
    wrong_owner = replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
    missing_project = replace(world["runtimes"]["own"], project_id=uuid4())
    attempts = [
        (world["runtimes"]["own"], _ids(world, "peer")[0]),
        (world["runtimes"]["own"], _ids(world, "foreign")[0]),
        (world["runtimes"]["own"], uuid4()),
        (world["runtimes"]["peer"], own_document),
        (wrong_owner, own_document),
        (missing_project, own_document),
    ]
    messages = set()
    for runtime, document in attempts:
        messages.add(
            _failure(lambda: _api().read_draft(runtime, document_id=document), 404, "not_found")
        )
        for expected, base in ((0, own_base), (1, own_base), (123, uuid4())):
            message = _failure(
                lambda: _api().save_draft(
                    runtime,
                    document_id=document,
                    expected_revision=expected,
                    base_version_id=base,
                    content_markdown=PRIVATE,
                ),
                404,
                "not_found",
            )
            assert str(document) not in message and str(base) not in message
            messages.add(message)
    assert len(messages) == 1
    assert _sources(world["engine"]) == before_sources
    assert _drafts(world["engine"]) == before_drafts


def test_project_transfer_moves_existing_draft_access_to_new_owner(run_world):
    world = run_world
    document, base = _ids(world)
    saved = _save(world)
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE projects SET owner_id=:owner WHERE id=:project"),
            {"owner": world["owners"]["foreign"], "project": world["projects"]["own"]},
        )
    before = _sources(world["engine"])
    _failure(lambda: _read(world), 404, "not_found")
    _failure(lambda: _save(world, revision=1), 404, "not_found")
    new_owner = replace(world["runtimes"]["own"], user_id=world["owners"]["foreign"])
    assert _api().read_draft(new_owner, document_id=document).model_dump() == saved.model_dump()
    updated = _api().save_draft(
        new_owner,
        document_id=document,
        expected_revision=1,
        base_version_id=base,
        content_markdown="Saved by the new project owner",
    )
    _snapshot(updated, document, base, 2, "Saved by the new project owner")
    assert _sources(world["engine"]) == before


def test_document_transfer_requires_its_new_project_runtime(run_world):
    world = run_world
    document, base = _ids(world)
    saved = _save(world)
    with world["engine"].begin() as connection:
        connection.execute(
            text("UPDATE documents SET project_id=:project WHERE id=:document"),
            {"project": world["projects"]["peer"], "document": document},
        )
    before = _sources(world["engine"])
    _failure(lambda: _read(world), 404, "not_found")
    _failure(lambda: _save(world, revision=1), 404, "not_found")
    assert _read(world, scope="peer").model_dump() == saved.model_dump()
    updated = _save(world, scope="peer", revision=1, content="Moved document draft")
    _snapshot(updated, document, base, 2, "Moved document draft")
    assert _sources(world["engine"]) == before


def test_save_argument_validation_is_strict_safe_and_precedes_database_access(
    run_world, monkeypatch
):
    world = run_world
    document, base = _ids(world)
    good = {
        "document_id": document,
        "base_version_id": base,
        "expected_revision": 0,
        "content_markdown": PRIVATE,
    }
    invalid = (
        [
            (field, value)
            for field in ("document_id", "base_version_id")
            for value in (None, str(document), document.hex, 0, True, b"uuid")
        ]
        + [
            ("expected_revision", value)
            for value in (None, True, False, 0.0, 1.0, "0", -1, MAX_EXPECTED_REVISION + 1)
        ]
        + [
            ("content_markdown", value)
            for value in (
                None,
                42,
                True,
                b"bytes",
                ["text"],
                {"text": PRIVATE},
                "\0",
                "\ud800",
                "\udfff",
            )
        ]
    )
    api = _api()
    connection_attempts = []

    def unexpected_connection(*args, **kwargs):
        connection_attempts.append(True)
        raise AssertionError("Invalid arguments must be rejected before database access")

    messages = set()
    with monkeypatch.context() as patch:
        patch.setattr(world["engine"], "connect", unexpected_connection)
        for field, value in invalid:
            arguments = {**good, field: value}
            messages.add(
                _failure(
                    lambda: api.save_draft(world["runtimes"]["own"], **arguments),
                    422,
                    "validation_error",
                )
            )
    assert not connection_attempts
    assert len(messages) == 1
    assert _drafts(world["engine"]) == []


def test_read_argument_validation_rejects_uuid_coercion_before_database_access(
    run_world, monkeypatch
):
    world = run_world
    document, _ = _ids(world)
    api = _api()
    connection_attempts = []

    def unexpected_connection(*args, **kwargs):
        connection_attempts.append(True)
        raise AssertionError("Invalid document ID must not access the database")

    messages = set()
    with monkeypatch.context() as patch:
        patch.setattr(world["engine"], "connect", unexpected_connection)
        for invalid in (None, str(document), document.hex, 0, True, document.bytes):
            messages.add(
                _failure(
                    lambda: api.read_draft(world["runtimes"]["own"], document_id=invalid),
                    422,
                    "validation_error",
                )
            )
    assert not connection_attempts
    assert len(messages) == 1


def test_database_time_is_refreshed_on_each_save_and_bigint_boundary_is_explicit(run_world):
    world = run_world
    document, base = _ids(world)
    with world["engine"].connect() as connection:
        lower = connection.scalar(text("SELECT clock_timestamp()"))
    first = _save(world)
    with world["engine"].connect() as connection:
        upper = connection.scalar(text("SELECT clock_timestamp()"))
    assert lower <= first.updated_at <= upper
    with world["engine"].begin() as connection:
        connection.execute(
            text(
                "UPDATE document_drafts SET revision=:revision, "
                "updated_at='2000-01-01 00:00:00+00' WHERE document_id=:document"
            ),
            {"revision": MAX_EXPECTED_REVISION, "document": document},
        )
        lower = connection.scalar(text("SELECT clock_timestamp()"))
    saved = _save(world, revision=MAX_EXPECTED_REVISION, content="Last BIGINT revision")
    with world["engine"].connect() as connection:
        upper = connection.scalar(text("SELECT clock_timestamp()"))
    _snapshot(saved, document, base, MAX_EXPECTED_REVISION + 1, "Last BIGINT revision")
    assert lower <= saved.updated_at <= upper
    _failure(lambda: _save(world, revision=MAX_EXPECTED_REVISION + 1), 422, "validation_error")
    assert _read(world).model_dump() == saved.model_dump()
