"""Native ordinary Word admission and all five historical source profiles."""

import importlib
import json
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_docx_analysis_runs_start import counts, finish, reject
from test_docx_analysis_runs_start import world as world
from test_docx_structured_runtime import created, set_source, source_record
from test_docx_visible_style_lists import fixture
from test_docx_visible_word import source as word_source

from ara.config import DatabaseSettings
from ara.docx_analysis.storage_codec import RetryCheckCommand
from ara.docx_analysis.visible_word._models import PROFILE
from ara.docx_analysis_worker.structured_fixture import fixture_execution


def api():
    return importlib.import_module("ara.docx_analysis_runs.word")


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
    factory = importlib.import_module("ara.docx_analysis_worker.supervisor.word_fixture")
    w = world["scopes"]["own"]
    return factory.create_word_fixture_supervisor(
        settings=DatabaseSettings(world["engine"].url.render_as_string(hide_password=False)),
        user_id=w["runtime"].user_id,
        project_id=w["runtime"].project_id,
        installation_id=installation,
        root=tmp_path,
    )


def test_word_saved_admission_is_idempotent_and_keeps_exact_source(world):
    raw = word_source("numbered")
    set_source(world, raw)
    key = uuid4()
    first = start(world, client_request_id=key)
    repeated = start(world, client_request_id=key, target_provider=None, execution=None)
    assert repeated.replayed and first.summary == repeated.summary and counts(world) == (1, 1)
    src = source_record(world, first.summary.run_id)
    assert src.profile == PROFILE and src.source_data == raw
    assert [x["level"] for x in json.loads(src.snapshot_data)["lists"]] == [0, 0]
    assert (first.summary.deadline_at - first.summary.created_at).total_seconds() == 300


def test_unsupported_word_does_not_enqueue_or_downgrade(world):
    from test_docx_visible_outline import definitions, level, paragraph, source

    raw = source(paragraph(level=1), definitions(level(0), level(1, text="%1.%2")))[0]
    set_source(world, raw)
    reject("unsupported_analysis_content", lambda: start(world), 422)
    assert counts(world) == (0, 0)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
def test_native_word_succeeds_and_owned_supervisor_reopens(world, tmp_path):
    from test_docx_analysis_supervisor_runtime import finished, submit, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    raw = word_source("numbered")
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
                assert body["schema_version"] == "docx-review/5" and body["profile"] == PROFILE
                assert [x["label"] for x in body["document_context"]["lists"]] == ["1.", "2."]
                assert (
                    body["findings"][0]["primary"]["quote"] == "Пользователь выбирает устройство."
                    and not body["no_findings"]
                )
        finally:
            assert s.shutdown(timeout=5)


@pytest.mark.skipif(sys.platform not in ("darwin", "win32"), reason="native host required")
@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_word_native_retry_keeps_each_original_profile_after_new_save(world, tmp_path, version):
    from test_docx_analysis_supervisor_runtime import finished, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    installation = uuid4()
    ledger.provision_new_database(
        world["engine"], installation_id=installation, expected_revision=1
    )

    module = importlib.import_module(
        {
            1: "ara.docx_analysis_runs",
            2: "ara.docx_analysis_runs.structured",
            3: "ara.docx_analysis_runs.outline",
            4: "ara.docx_analysis_runs.style_lists",
            5: "ara.docx_analysis_runs.word",
        }[version]
    )
    if version > 1:
        from test_docx_outline_integration import fixture as old_fixture

        set_source(
            world,
            created()
            if version == 2
            else old_fixture()[0]
            if version == 3
            else fixture()[0]
            if version == 4
            else word_source("numbered"),
        )
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
    set_source(world, word_source("plain"), 8)
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
def test_word_native_stop_preserves_saved_source_without_result(world, tmp_path):
    from test_docx_analysis_supervisor_runtime import finished, submit, wait_for

    from ara.docx_analysis_worker.supervisor import ledger

    raw = word_source("numbered")
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
