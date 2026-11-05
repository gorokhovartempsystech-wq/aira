"""Structured saved admission and native fixture2 keep original source identity."""

import importlib
import json
import sys
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_analysis_runs_start import counts, finish, reject
from test_docx_analysis_runs_start import world as world

from ara.config import DatabaseSettings
from ara.docx_analysis.storage_codec import RetryCheckCommand
from ara.docx_analysis.visible_lists._models import PROFILE as LIST_PROFILE
from ara.docx_analysis.visible_main._models import PROFILE
from ara.docx_analysis_worker.structured_fixture import fixture_execution
from ara.docx_package.creation import NewParagraph, create_docx


def api():
    return importlib.import_module("ara.docx_analysis_runs.structured")


def factory():
    return importlib.import_module("ara.docx_analysis_worker.supervisor.structured_fixture")


def created():
    return create_docx(
        (
            NewParagraph("Requirements", "heading1"),
            NewParagraph("First requirement", "numbered"),
            NewParagraph("Second requirement", "numbered"),
            NewParagraph("Body text", "body"),
        )
    )


def set_source(world, raw, revision=7):
    w = world["scopes"]["own"]
    digest = sha256(raw).hexdigest()
    with world["engine"].begin() as conn:
        conn.execute(
            text(
                "UPDATE docx_documents SET storage_revision=:v,current_data=:data,"
                "current_sha256=:sha WHERE id=:id"
            ),
            dict(v=revision, data=raw, sha=digest, id=w["doc"]),
        )
    w["command"] = replace(w["command"], storage_revision=revision, source_sha256=digest)
    w["target"] = replace(w["target"], storage_revision=revision, sha256=digest, data=raw)
    return w


def start(world, **changes):
    w = world["scopes"]["own"]
    return api().start_saved(
        w["runtime"],
        **(
            dict(
                client_request_id=uuid4(),
                command=w["command"],
                target_provider=lambda: w["target"],
                execution=fixture_execution(),
            )
            | changes
        ),
    )


def source_record(world, run):
    from ara.docx_analysis_runs import get_source

    w = world["scopes"]["own"]
    return get_source(w["runtime"], document_id=w["doc"], run_id=run)


def make(world, tmp_path, installation):
    w = world["scopes"]["own"]
    return factory().create_structured_fixture_supervisor(
        settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
        user_id=w["runtime"].user_id,
        project_id=w["runtime"].project_id,
        installation_id=installation,
        root=tmp_path,
    )


def test_saved_start_keeps_structured_manifest_and_replays_without_provider(world):
    raw = created()
    set_source(world, raw)
    key = uuid4()
    first = start(world, client_request_id=key)
    replay = start(world, client_request_id=key, target_provider=None, execution=None)
    assert not first.replayed and replay.replayed and first.summary == replay.summary
    record = source_record(world, first.summary.run_id)
    assert record.profile == LIST_PROFILE and record.source_data == raw
    assert len(json.loads(record.snapshot_data)["lists"]) == 2
    assert counts(world) == (1, 1)
    assert (first.summary.deadline_at - first.summary.created_at).total_seconds() == 300


def test_old_default_start_does_not_implicitly_enable_the_structured_profile(world):
    from ara.docx_analysis_runs import start_saved

    w = set_source(world, created())
    reject(
        "unsupported_analysis_content",
        lambda: start_saved(
            w["runtime"],
            client_request_id=uuid4(),
            command=w["command"],
            target_provider=lambda: w["target"],
            execution=fixture_execution(),
        ),
        422,
    )
    assert counts(world) == (0, 0)


def test_saved_target_is_used_even_when_current_document_changes_after_save(world):
    w = set_source(world, created())
    cmd, target = w["command"], w["target"]
    set_source(world, create_docx((NewParagraph("Later document", "body"),)), 8)
    out = start(world, command=cmd, target_provider=lambda: target)
    src = source_record(world, out.summary.run_id)
    assert (
        src.source_data == target.data
        and src.storage_revision == 7
        and src.source_sha256 == cmd.source_sha256
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_retry_keeps_original_profile_and_snapshot_after_current_document_changes(world, legacy):
    from ara.docx_analysis_runs import start_saved
    from ara.docx_analysis_worker.review_fixture import fixture_execution as legacy_execution

    w = world["scopes"]["own"]
    if legacy:
        first = start_saved(
            w["runtime"],
            client_request_id=uuid4(),
            command=w["command"],
            target_provider=lambda: w["target"],
            execution=legacy_execution(),
        )
    else:
        set_source(world, created())
        first = start(world)
    original = source_record(world, first.summary.run_id)
    cmd = RetryCheckCommand(w["doc"], first.summary.run_id)
    reject(
        "analysis_in_progress",
        lambda: api().retry_run(
            w["runtime"], client_request_id=uuid4(), command=cmd, execution=fixture_execution()
        ),
        409,
    )
    finish(world, first.summary.run_id)
    set_source(world, create_docx((NewParagraph("Current changed document", "body"),)), 8)
    key = uuid4()
    second = api().retry_run(
        w["runtime"], client_request_id=key, command=cmd, execution=fixture_execution()
    )
    replay = api().retry_run(w["runtime"], client_request_id=key, command=cmd, execution=None)
    restored = source_record(world, second.summary.run_id)
    assert replay.replayed and replay.summary == second.summary
    assert (
        restored.source_data == original.source_data
        and restored.snapshot_data == original.snapshot_data
    )
    assert restored.profile == (PROFILE if legacy else LIST_PROFILE)
    assert restored.storage_revision == original.storage_revision == 7
    assert restored.source_sha256 == original.source_sha256
    assert second.summary.retry_of_run_id == first.summary.run_id
    if legacy:
        assert restored.execution_spec != original.execution_spec
    assert counts(world) == (1, 2)


def test_new_entry_replays_a_previously_accepted_old_policy_without_upgrading_it(world):
    from ara.docx_analysis_runs import start_saved

    w = world["scopes"]["own"]
    key = uuid4()
    first = start_saved(
        w["runtime"],
        client_request_id=key,
        command=w["command"],
        target_provider=lambda: w["target"],
        execution=fixture_execution(),
    )
    new = start(world, client_request_id=key, target_provider=None, execution=None)
    assert new.replayed and new.summary == first.summary
    assert source_record(world, new.summary.run_id).profile == PROFILE
    assert counts(world) == (1, 1)


@pytest.mark.parametrize(
    "body,code",
    [((), "empty_document"), ((NewParagraph("One", "numbered"),), "saved_target_conflict")],
)
def test_empty_and_target_mismatch_do_not_enqueue(world, body, code):
    w = set_source(world, create_docx(body))
    kw = (
        {"command": replace(w["command"], session_revision=1)}
        if code == "saved_target_conflict"
        else {}
    )
    reject(code, lambda: start(world, **kw), 409 if code == "saved_target_conflict" else 422)
    assert counts(world) == (0, 0)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_structured_success_restart_and_new_run_preserve_context(world, tmp_path):
    from test_docx_analysis_supervisor_runtime import finished, submit, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    set_source(world, created())
    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    for number in (1, 2):
        s = make(world, tmp_path, installation)
        assert s.view().phase == "new" and s.view().fixture
        try:
            s.start()
            wait_for(lambda: s.view().phase == "ready")
            ticket = submit(s, world)
            result = finished(s, ticket)
            assert result.sql_state.summary.status == "succeeded"
            wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")
            src = source_record(world, result.run_id)
            assert src.profile == LIST_PROFILE
            with world["engine"].connect() as conn:
                rows = conn.execute(
                    text("SELECT result_data,no_findings FROM docx_analysis_results")
                ).all()
            assert len(rows) == number
            for row in rows:
                body = json.loads(bytes(row.result_data))
                assert body["schema_version"] == "docx-review/2" and body["profile"] == LIST_PROFILE
                assert len(body["document_context"]["lists"]) == 2 and not row.no_findings
                assert body["provenance"]["models_version"] == "aira-review-fixture-2"
                assert body["findings"][0]["primary"]["quote"] == "First requirement"
        finally:
            assert s.shutdown(timeout=5)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_immediate_stop_preserves_structured_source_without_result(world, tmp_path):
    from test_docx_analysis_supervisor_runtime import finished, submit, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    set_source(world, created())
    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    s = make(world, tmp_path, installation)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        ticket = submit(s, world)
        s.stop(ticket)
        out = finished(s, ticket)
        assert out.sql_state.summary.status == "cancelled"
        src = source_record(world, out.run_id)
        assert (
            src.profile == LIST_PROFILE and src.source_data == world["scopes"]["own"]["target"].data
        )
        with world["engine"].connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM docx_analysis_results")) == 0
        assert counts(world) == (1, 1)
    finally:
        assert s.shutdown(timeout=5)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
@pytest.mark.parametrize("legacy", [False, True])
def test_native_retry_runs_original_legacy_or_structured_snapshot_after_new_save(
    world, tmp_path, legacy
):
    from test_docx_analysis_supervisor_runtime import finished, wait_for

    from ara.docx_analysis_runs import start_saved
    from ara.docx_analysis_worker.review_fixture import fixture_execution as legacy_execution
    from ara.docx_analysis_worker.supervisor import ledger

    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    w = world["scopes"]["own"]
    if legacy:
        parent = start_saved(
            w["runtime"],
            client_request_id=uuid4(),
            command=w["command"],
            target_provider=lambda: w["target"],
            execution=legacy_execution(),
        )
    else:
        set_source(world, created())
        parent = start(world)
    original = source_record(world, parent.summary.run_id)
    finish(world, parent.summary.run_id)
    set_source(world, create_docx((NewParagraph("Completely new current text", "body"),)), 8)
    s = make(world, tmp_path, installation)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        ticket = s.retry(
            client_request_id=uuid4(), command=RetryCheckCommand(w["doc"], parent.summary.run_id)
        )
        out = finished(s, ticket)
        assert out.sql_state.summary.status == "succeeded"
        restored = source_record(world, out.run_id)
        assert (
            restored.source_data == original.source_data
            and restored.snapshot_data == original.snapshot_data
        )
        assert restored.profile == (PROFILE if legacy else LIST_PROFILE)
        assert restored.storage_revision == 7
        with world["engine"].connect() as conn:
            data = bytes(
                conn.scalar(
                    text("SELECT result_data FROM docx_analysis_results WHERE run_id=:id"),
                    {"id": out.run_id},
                )
            )
        body = json.loads(data)
        assert body["schema_version"] == ("docx-review/1" if legacy else "docx-review/2")
        assert body["provenance"]["models_version"] == "aira-review-fixture-2"
        assert body["findings"][0]["primary"]["quote"] == (
            "abcd" if legacy else "First requirement"
        )
        assert "Completely new current text" not in data.decode()
    finally:
        assert s.shutdown(timeout=5)
