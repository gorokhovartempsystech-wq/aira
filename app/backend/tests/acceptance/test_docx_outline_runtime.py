"""Native fixture admission and retries retain the exact accepted outline source."""

import importlib
import json
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_analysis_runs_start import counts, finish, reject
from test_docx_analysis_runs_start import world as world
from test_docx_outline_integration import fixture
from test_docx_structured_runtime import created, set_source, source_record

from ara.config import DatabaseSettings
from ara.docx_analysis.storage_codec import RetryCheckCommand
from ara.docx_analysis.visible_outline._models import PROFILE
from ara.docx_analysis_worker.structured_fixture import fixture_execution


def api():
    return importlib.import_module("ara.docx_analysis_runs.outline")


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


def make(world, tmp_path, installation):
    factory = importlib.import_module("ara.docx_analysis_worker.supervisor.outline_fixture")
    w = world["scopes"]["own"]
    return factory.create_outline_fixture_supervisor(
        settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
        user_id=w["runtime"].user_id,
        project_id=w["runtime"].project_id,
        installation_id=installation,
        root=tmp_path,
    )


def test_outline_saved_admission_is_idempotent_and_keeps_exact_source(world):
    raw = fixture()[0]
    set_source(world, raw)
    key = uuid4()
    first = start(world, client_request_id=key)
    repeated = start(world, client_request_id=key, target_provider=None, execution=None)
    assert repeated.replayed and first.summary == repeated.summary and counts(world) == (1, 1)
    src = source_record(world, first.summary.run_id)
    assert src.profile == PROFILE and src.source_data == raw
    assert [x["level"] for x in json.loads(src.snapshot_data)["lists"]] == [0, 1]
    assert (first.summary.deadline_at - first.summary.created_at).total_seconds() == 300


def test_unsupported_outline_does_not_enqueue_or_downgrade(world):
    from test_docx_visible_outline import definitions, level, paragraph, source

    raw = source(paragraph(level=1), definitions(level(0), level(1, text="%1.%2")))[0]
    set_source(world, raw)
    reject("unsupported_analysis_content", lambda: start(world), 422)
    assert counts(world) == (0, 0)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_outline_succeeds_and_owned_supervisor_reopens(world, tmp_path):
    from test_docx_analysis_supervisor_runtime import finished, submit, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    raw = fixture()[0]
    set_source(world, raw)
    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )
    for number in (1, 2):
        s = make(world, tmp_path, installation)
        try:
            s.start()
            wait_for(lambda: s.view().phase == "ready")
            out = finished(s, submit(s, world))
            assert out.sql_state.summary.status == "succeeded"
            wait_for(lambda: ledger.read_fence(world["engine"]).phase == "clean")
            assert source_record(world, out.run_id).source_data == raw
            with world["engine"].connect() as conn:
                rows = conn.execute(text("SELECT result_data FROM docx_analysis_results")).all()
            assert len(rows) == number
            for row in rows:
                body = json.loads(bytes(row.result_data))
                assert body["schema_version"] == "docx-review/3" and body["profile"] == PROFILE
                assert [x["label"] for x in body["document_context"]["lists"]] == ["IV.", "IV.i"]
                assert body["findings"][0]["primary"]["quote"] == "abcd" and not body["no_findings"]
        finally:
            assert s.shutdown(timeout=5)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
@pytest.mark.parametrize("version", [1, 2, 3])
def test_outline_native_retry_keeps_each_original_profile_after_new_save(world, tmp_path, version):
    from test_docx_analysis_supervisor_runtime import finished, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )

    module = importlib.import_module(
        "ara.docx_analysis_runs"
        if version == 1
        else "ara.docx_analysis_runs.structured"
        if version == 2
        else "ara.docx_analysis_runs.outline"
    )
    if version > 1:
        set_source(world, created() if version == 2 else fixture()[0])
    w = world["scopes"]["own"]
    first = module.start_saved(
        w["runtime"],
        client_request_id=uuid4(),
        command=w["command"],
        target_provider=lambda: w["target"],
        execution=fixture_execution(),
    )
    original = source_record(world, first.summary.run_id)
    finish(world, first.summary.run_id)
    set_source(world, fixture(child="Later text")[0], 8)
    s = make(world, tmp_path, installation)
    try:
        s.start()
        wait_for(lambda: s.view().phase == "ready")
        ticket = s.retry(
            client_request_id=uuid4(), command=RetryCheckCommand(w["doc"], first.summary.run_id)
        )
        out = finished(s, ticket)
        assert out.sql_state.summary.status == "succeeded"
        src = source_record(world, out.run_id)
        assert (
            src.source_data == original.source_data and src.snapshot_data == original.snapshot_data
        )
        assert (
            src.profile == original.profile
            and src.storage_revision == original.storage_revision == 7
        )
        with world["engine"].connect() as conn:
            data = bytes(
                conn.scalar(
                    text("SELECT result_data FROM docx_analysis_results WHERE run_id=:id"),
                    {"id": out.run_id},
                )
            )
        body = json.loads(data)
        assert (
            body["schema_version"] == f"docx-review/{version}"
            and body["profile"] == original.profile
        )
        assert body["provenance"]["models_version"] == "aira-review-fixture-2"
    finally:
        assert s.shutdown(timeout=5)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_outline_native_stop_preserves_saved_source_without_result(world, tmp_path):
    from test_docx_analysis_supervisor_runtime import finished, submit, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    raw = fixture()[0]
    set_source(world, raw)
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
        assert source_record(world, out.run_id).source_data == raw
        with world["engine"].connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM docx_analysis_results")) == 0
    finally:
        assert s.shutdown(timeout=5)
