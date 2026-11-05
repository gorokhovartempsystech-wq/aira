"""Frozen B3A: scoped durable enqueue and replay of an exact saved DOCX."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_docx_analysis_storage_codec import command, execution
from test_docx_review_v1 import fixture
from test_docx_storage_migrations import insert_row

from ara.documents.runtime import DocumentRuntime
from ara.documents.storage import DocumentError
from ara.docx_analysis.visible_main import build_visible_snapshot
from ara.docx_editor._models import SavedTarget


def api():
    return import_module("ara.docx_analysis_runs")


@pytest.fixture
def world(pg_engine):
    raw, _ = fixture()
    users = [uuid4(), uuid4()]
    scopes = {}
    with pg_engine.begin() as conn:
        for u in users:
            conn.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": u})
        for name, owner in [("own", users[0]), ("peer", users[0]), ("foreign", users[1])]:
            project, doc = uuid4(), uuid4()
            conn.execute(
                text("INSERT INTO projects(id,owner_id,name) VALUES(:p,:o,'Synthetic')"),
                {"p": project, "o": owner},
            )
            insert_row(
                conn,
                project,
                id=doc,
                storage_revision=7,
                current_data=raw,
                current_sha256=sha256(raw).hexdigest(),
            )
            runtime = DocumentRuntime(
                engine=pg_engine, user_id=owner, project_id=project, mode="local"
            )
            s = build_visible_snapshot(
                raw, document_id=doc, storage_revision=7, source_sha256=sha256(raw).hexdigest()
            )
            cmd = command(s)
            target = SavedTarget(
                cmd.registry_id,
                doc,
                cmd.session_id,
                cmd.save_command_id,
                cmd.command_sequence,
                cmd.session_revision,
                7,
                s.source_sha256,
                raw,
            )
            scopes[name] = dict(runtime=runtime, doc=doc, command=cmd, target=target)
    return dict(engine=pg_engine, scopes=scopes)


def start(world, name="own", **changes):
    w = world["scopes"][name]
    return api().start_saved(
        w["runtime"],
        **(
            dict(
                client_request_id=uuid4(),
                command=w["command"],
                target_provider=lambda: w["target"],
                execution=execution(),
            )
            | changes
        ),
    )


def reject(code, call, status=None):
    with pytest.raises(DocumentError) as caught:
        call()
    assert caught.value.code == code
    if status is not None:
        assert caught.value.status == status
    assert "Synthetic" not in str(caught.value)


def counts(world):
    with world["engine"].connect() as conn:
        return tuple(
            conn.scalar(text("SELECT count(*) FROM docx_analysis_" + t))
            for t in ("sources", "runs")
        )


def finish(world, run_id):
    with world["engine"].begin() as conn:
        conn.execute(
            text(
                "UPDATE docx_analysis_runs SET status='failed',stage='failed',fence=1,"
                "error_code='interrupted',finished_at=clock_timestamp() WHERE id=:id"
            ),
            {"id": run_id},
        )


def test_enqueue_and_durable_replay_precede_provider_and_config(world):
    key = uuid4()
    w = world["scopes"]["own"]
    first = start(world, client_request_id=key)
    again = start(world, client_request_id=key, target_provider=None, execution=None)
    assert first.replayed is False and again.replayed is True
    assert first.summary == again.summary
    assert (
        first.summary.storage_revision == 7
        and first.summary.status == first.summary.stage == "queued"
    )
    assert (first.summary.deadline_at - first.summary.created_at).total_seconds() == 300
    assert counts(world) == (1, 1)
    assert (
        api().get_run(w["runtime"], document_id=w["doc"], run_id=first.summary.run_id)
        == first.summary
    )


def test_same_key_altered_body_conflicts_without_touching_registry(world):
    key = uuid4()
    start(world, client_request_id=key)
    reject(
        "idempotency_conflict",
        lambda: start(
            world,
            client_request_id=key,
            command=replace(world["scopes"]["own"]["command"], command_sequence=3),
            target_provider=None,
        ),
        409,
    )
    assert counts(world) == (1, 1)


@pytest.mark.parametrize(
    "field",
    [
        "registry_id",
        "session_id",
        "save_command_id",
        "command_sequence",
        "session_revision",
        "storage_revision",
        "source_sha256",
    ],
)
def test_saved_target_mismatch_never_enqueues(world, field):
    cmd = world["scopes"]["own"]["command"]
    bad = (
        uuid4()
        if field.endswith("_id")
        else "b" * 64
        if field == "source_sha256"
        else getattr(cmd, field) + 1
    )
    reject("saved_target_conflict", lambda: start(world, command=replace(cmd, **{field: bad})), 409)
    assert counts(world) == (0, 0)


def test_source_is_exact_saved_copy_after_current_changes(world):
    w = world["scopes"]["own"]
    raw = w["target"].data
    with world["engine"].begin() as conn:
        conn.execute(
            text(
                "UPDATE docx_documents SET storage_revision=8,current_data=:v,"
                "current_sha256=:h WHERE id=:id"
            ),
            {
                "id": w["doc"],
                "v": b"Newer synthetic version",
                "h": sha256(b"Newer synthetic version").hexdigest(),
            },
        )
    out = start(world)
    src = api().get_source(w["runtime"], document_id=w["doc"], run_id=out.summary.run_id)
    assert src.source_data == raw and src.storage_revision == 7
    assert src.source_sha256 == w["target"].sha256


def test_metadata_read_does_not_load_content_or_depend_on_source_validity(world):
    w = world["scopes"]["own"]
    out = start(world)
    with world["engine"].begin() as conn:
        conn.execute(text("UPDATE docx_analysis_sources SET source_data=:v"), {"v": b"Damaged"})
    statements = []

    def observe(c, cursor, statement, params, context, many):
        statements.append(statement.lower())

    event.listen(world["engine"], "before_cursor_execute", observe)
    try:
        assert (
            api().get_run(w["runtime"], document_id=w["doc"], run_id=out.summary.run_id)
            == out.summary
        )
    finally:
        event.remove(world["engine"], "before_cursor_execute", observe)
    for statement in statements:
        assert not any(
            n in statement
            for n in ("source_data", "snapshot_data", "current_data", "original_data")
        )
    reject(
        "storage_error",
        lambda: api().get_source(w["runtime"], document_id=w["doc"], run_id=out.summary.run_id),
        500,
    )


@pytest.mark.parametrize("scope", ["peer", "foreign"])
def test_read_and_start_are_scoped_before_provider(world, scope):
    out = start(world)
    own = world["scopes"]["own"]
    other = world["scopes"][scope]
    reject(
        "not_found",
        lambda: api().get_run(other["runtime"], document_id=own["doc"], run_id=out.summary.run_id),
        404,
    )
    reject(
        "not_found",
        lambda: api().start_saved(
            other["runtime"],
            client_request_id=uuid4(),
            command=own["command"],
            target_provider=None,
            execution=None,
        ),
        404,
    )


def test_retry_is_new_run_of_parent_source_with_new_deadline(world):
    w = world["scopes"]["own"]
    first = start(world)
    cmd = import_module("ara.docx_analysis.storage_codec").RetryCheckCommand(
        w["doc"], first.summary.run_id
    )
    reject(
        "analysis_in_progress",
        lambda: api().retry_run(
            w["runtime"], client_request_id=uuid4(), command=cmd, execution=execution()
        ),
        409,
    )
    finish(world, first.summary.run_id)
    second = api().retry_run(
        w["runtime"], client_request_id=uuid4(), command=cmd, execution=execution()
    )
    assert second.summary.run_id != first.summary.run_id
    assert (
        second.summary.retry_of_run_id == first.summary.run_id
        and second.summary.start_kind == "retry"
    )
    assert (
        second.summary.accepted_order == 2 and second.summary.created_at > first.summary.created_at
    )
    assert second.summary.source_sha256 == first.summary.source_sha256
    assert counts(world) == (1, 2)


def test_new_key_during_active_run_is_not_accepted(world):
    first = start(world)
    reject("analysis_in_progress", lambda: start(world), 409)
    finish(world, first.summary.run_id)
    next_run = start(world)
    assert next_run.summary.accepted_order == 2 and counts(world) == (1, 2)


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_enqueues_are_atomic(world, same_key):
    barrier = Barrier(2)
    key = uuid4()

    def provider():
        barrier.wait(timeout=5)
        return world["scopes"]["own"]["target"]

    def worker():
        try:
            return start(
                world, client_request_id=key if same_key else uuid4(), target_provider=provider
            )
        except DocumentError as e:
            return e

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [f.result(timeout=15) for f in futures]
    if same_key:
        assert results[0].summary.run_id == results[1].summary.run_id
        assert sorted(r.replayed for r in results) == [False, True]
    else:
        assert sum(isinstance(r, DocumentError) for r in results) == 1
        assert (
            next(r for r in results if isinstance(r, DocumentError)).code == "analysis_in_progress"
        )
    assert counts(world) == (1, 1)


def test_queue_cap_is_shared_across_projects(world):
    start(world, queue_limit=1)
    reject("analysis_queue_full", lambda: start(world, "peer", queue_limit=1), 503)
    assert counts(world) == (1, 1)


def test_provider_can_commit_matching_request_then_fail_and_replay_wins(world):
    key = uuid4()
    accepted = []

    def provider():
        accepted.append(start(world, client_request_id=key))
        raise DocumentError(410, "editor_session_expired", "Editor session has expired")

    replay = start(world, client_request_id=key, target_provider=provider)
    assert replay.replayed and replay.summary == accepted[0].summary
    assert counts(world) == (1, 1)


def test_ownership_change_during_provider_prevents_commit(world):
    w = world["scopes"]["own"]
    other = world["scopes"]["foreign"]

    def provider():
        with world["engine"].begin() as conn:
            conn.execute(
                text("UPDATE projects SET owner_id=:o WHERE id=:p"),
                {"o": other["runtime"].user_id, "p": w["runtime"].project_id},
            )
        return w["target"]

    reject("not_found", lambda: start(world, target_provider=provider), 404)
    assert counts(world) == (0, 0)


def test_source_hash_collision_is_not_overwritten(world):
    w = world["scopes"]["own"]
    with world["engine"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO docx_analysis_sources(document_id,source_sha256,source_data) "
                "VALUES(:id,:h,:v)"
            ),
            {"id": w["doc"], "h": w["target"].sha256, "v": b"Wrong bytes"},
        )
    reject("storage_error", lambda: start(world), 500)
    assert counts(world) == (1, 0)


def test_failed_provider_has_no_partial_rows(world):
    def provider():
        raise RuntimeError("Synthetic private failure")

    reject("storage_error", lambda: start(world, target_provider=provider), 500)
    assert counts(world) == (0, 0)
